from typing import List, Union

import torch
import torch.nn as nn
from torch.distributed import ProcessGroup

<<<<<<< HEAD
from .parallel_module import ParallelModule
=======
from .layers import ParallelModule
>>>>>>> [shardformer] refactored embedding and dropout to parallel module (#4013)
from .utils import create_randomizer_with_offset

__all__ = ['Dropout1D']


class Dropout1D(ParallelModule, nn.Dropout):
    """
    The Dropout Layer will apply dropout mask to the input tensor. The dropout mask is generated with
    randomness on different ranks of the given process group. This can avoid the same dropout mask is generated
    and applied on the same position of different ranks, leading to poor convergence performance.

    Args:
        p (float): probability of an element to be zeroed. Defaults to 0.5.
        inplace (bool): If set to True, will do this operation in-place. Defaults to False.
        process_group (ProcessGroup): the process group to be used for generating randomness. Defaults to None.
    """

    def __init__(self, p: float = 0.5, inplace: bool = False, process_group: ProcessGroup = None):
        # init with nn.Dropout
        super(nn.Dropout, self).__init__(p=p, inplace=inplace)

        # offset the seed with randomizer index and rank
        seed = torch.random.initial_seed()
        self.randomizer = create_randomizer_with_offset(seed, process_group=process_group)

    @staticmethod
    def from_native_module(module: nn.Dropout,
                           process_group: Union[ProcessGroup, List[ProcessGroup]] = None) -> "Dropout1D":
        """
        Create a Dropout1D layer from a native dropout layer.
        """
        p = module.p
        inplace = module.inplace
        return Dropout1D(p=p, inplace=inplace, process_group=process_group)

    def forward(self, input):
        with self.randomizer.fork_rng():
            input = super().forward(input)
        return input
