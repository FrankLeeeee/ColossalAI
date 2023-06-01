import torch
import torch.distributed as dist
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Function


class DistCrossEntropy(Function):
    r"""
    Overwrite the forward and backward function to calculate the cross entropy loss before gather

    Args:
        Function (:class:`torch.autograd.Function`): default
    """

    @staticmethod
    def forward(ctx, vocab_logits: torch.Tensor, target: torch.Tensor):
        r"""
        Calculate the cross entropy loss before gather, the origin loss function is as follows:
        loss = -log(exp(x[class])/sum(exp(x[i]))
        and can be rewrite as:
        loss = log(sum(exp(x[i])) - x[class]

        To avoid the `nan` of log(sim(exp(x[i]))), we minus the max of x[i]

        Args:
            vocab_logits (:class:`torch.Tensor`): The logits of the vocabulary, shape is
              [batch_size, seq_len, vocab_size]
            labels (:class:`torch.Tensor`): The labels of the vocabulary, shape is
              [batch_size, seq_len]

        Returns:
            :class:`torch.Tensor`: The cross entropy loss
        """
        # get the max
        logits_max = torch.max(vocab_logits, dim=-1)[0]
        dist.all_reduce(logits_max, op=dist.ReduceOp.MAX)

        # minus the max to avoid the result of sum of exp is too large and the log is nan
        vocab_logits = vocab_logits - logits_max.unsqueeze(dim=-1)

        # mask the target in the local device
        partition_vocab_size = vocab_logits.size()[-1]
        rank = dist.get_rank()
        world_size = dist.get_world_size()
        global_vocab_size = partition_vocab_size * world_size

        # [down, up) => false, other device and -100 => true
        delta = (global_vocab_size + world_size - 1) // world_size
        down_shreshold = rank * delta
        up_shreshold = down_shreshold + delta
        mask = (target < down_shreshold) | (target >= up_shreshold)
        masked_target = target.clone() - down_shreshold
        masked_target[mask] = 0

        # reshape the logist and target
        # reshape the vocab_logits to [bath_size * seq_len, vocab_size]
        # reshape the labels to [bath_size * seq_len]
        logits_2d = vocab_logits.view(-1, partition_vocab_size)
        masked_target_1d = masked_target.view(-1)

        # extract the x[class] and set the x[other device] to zero
        pred_logits_1d = logits_2d[torch.arange(start=0, end=logits_2d.shape[0], device=logits_2d.device),
                                   masked_target_1d]
        pred_logits_1d = pred_logits_1d.clone().contiguous()
        pred_logits = pred_logits_1d.view_as(target)
        pred_logits[mask] = 0.0

        # allreduce the get all x(i,y)
        dist.all_reduce(pred_logits, op=dist.ReduceOp.SUM)
        exp_logits = vocab_logits
        torch.exp(vocab_logits, out=exp_logits)
        sum_exp_logits = torch.sum(exp_logits, dim=-1)
        dist.all_reduce(sum_exp_logits, op=dist.ReduceOp.SUM)

        # calculate the loss
        # loss = log(sum(exp(x[i]))) - x[class]
        loss = torch.log(sum_exp_logits) - pred_logits
        loss = torch.sum(loss).div_(loss.numel())

        # caculate the softmax
        exp_logits.div_(sum_exp_logits.unsqueeze(dim=-1))
        ctx.save_for_backward(exp_logits, mask, masked_target_1d)

        return loss

    @staticmethod
    def backward(ctx, grad_output):
        # retrieve the saved tensors
        exp_logits, mask, masked_target_1d = ctx.saved_tensors

        # use exp logits as the input grad
        grad_logits = exp_logits
        partion_vocab_size = grad_logits.shape[-1]
        grad_logits_2d = grad_logits.view(-1, partion_vocab_size)

        update = 1.0 - mask.view(-1).float()
        grad_logits_2d[torch.arange(0, grad_logits_2d.shape[0]), masked_target_1d] -= update

        grad_logits.mul_(grad_output.unsqueeze(dim=-1))
        return grad_logits, None, None


def applyDistCrossEntropy(vocab_logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    return DistCrossEntropy.apply(vocab_logits, labels)
