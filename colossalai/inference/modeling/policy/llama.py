from functools import partial

from transformers.models.llama.modeling_llama import (
    LlamaAttention,
    LlamaDecoderLayer,
    LlamaFlashAttention2,
    LlamaForCausalLM,
    LlamaModel,
    LlamaSdpaAttention,
)

from colossalai.inference.modeling.models.llama import (
    llama_attn_forward,
    llama_causal_lm_forward,
    llama_decoder_layer_forward,
    llama_model_forward,
)
from colossalai.shardformer.policies.base_policy import ModulePolicyDescription, SubModuleReplacementDescription

# import colossalai
from colossalai.shardformer.policies.llama import LlamaForCausalLMPolicy


class LlamaModelInferPolicy(LlamaForCausalLMPolicy):
    def __init__(self) -> None:
        super().__init__()

    def module_policy(self):
        policy = super().module_policy()
        decoder_attribute_replacement = {
            "self_attn.hidden_size": self.model.config.hidden_size // self.shard_config.tensor_parallel_size,
            "self_attn.num_heads": self.model.config.num_attention_heads // self.shard_config.tensor_parallel_size,
            "self_attn.num_key_value_heads": self.model.config.num_key_value_heads
            // self.shard_config.tensor_parallel_size,
        }
        if self.shard_config.extra_kwargs.get("quant", None) == "gptq":
            from colossalai.inference.quant.gptq.cai_gptq import ColCaiQuantLinear, RowCaiQuantLinear

            policy[LlamaDecoderLayer] = ModulePolicyDescription(
                attribute_replacement=decoder_attribute_replacement,
                sub_module_replacement=[
                    SubModuleReplacementDescription(
                        suffix="self_attn.q_proj",
                        target_module=ColCaiQuantLinear,
                        kwargs={"split_num": 1},
                    ),
                    SubModuleReplacementDescription(
                        suffix="self_attn.k_proj",
                        target_module=ColCaiQuantLinear,
                        kwargs={"split_num": 1},
                    ),
                    SubModuleReplacementDescription(
                        suffix="self_attn.v_proj",
                        target_module=ColCaiQuantLinear,
                        kwargs={"split_num": 1},
                    ),
                    SubModuleReplacementDescription(
                        suffix="self_attn.o_proj",
                        target_module=RowCaiQuantLinear,
                        kwargs={"split_num": 1},
                    ),
                    SubModuleReplacementDescription(
                        suffix="mlp.gate_proj",
                        target_module=ColCaiQuantLinear,
                        kwargs={"split_num": 1},
                    ),
                    SubModuleReplacementDescription(
                        suffix="mlp.up_proj",
                        target_module=ColCaiQuantLinear,
                        kwargs={"split_num": 1},
                    ),
                    SubModuleReplacementDescription(
                        suffix="mlp.down_proj",
                        target_module=RowCaiQuantLinear,
                        kwargs={"split_num": 1},
                    ),
                ],
            )

        elif self.shard_config.extra_kwargs.get("quant", None) == "smoothquant":
            from colossalai.inference.quant.smoothquant.models.llama import LlamaSmoothquantDecoderLayer
            from colossalai.inference.quant.smoothquant.models.parallel_linear import (
                ColW8A8BFP32OFP32Linear,
                RowW8A8B8O8Linear,
                RowW8A8BFP32O32LinearSiLU,
                RowW8A8BFP32OFP32Linear,
            )

            policy[LlamaSmoothquantDecoderLayer] = ModulePolicyDescription(
                attribute_replacement=decoder_attribute_replacement,
                sub_module_replacement=[
                    SubModuleReplacementDescription(
                        suffix="self_attn.q_proj",
                        target_module=RowW8A8B8O8Linear,
                        kwargs={"split_num": 1},
                    ),
                    SubModuleReplacementDescription(
                        suffix="self_attn.k_proj",
                        target_module=RowW8A8B8O8Linear,
                        kwargs={"split_num": 1},
                    ),
                    SubModuleReplacementDescription(
                        suffix="self_attn.v_proj",
                        target_module=RowW8A8B8O8Linear,
                        kwargs={"split_num": 1},
                    ),
                    SubModuleReplacementDescription(
                        suffix="self_attn.o_proj",
                        target_module=ColW8A8BFP32OFP32Linear,
                        kwargs={"split_num": 1},
                    ),
                    SubModuleReplacementDescription(
                        suffix="mlp.gate_proj",
                        target_module=RowW8A8BFP32O32LinearSiLU,
                        kwargs={"split_num": 1},
                    ),
                    SubModuleReplacementDescription(
                        suffix="mlp.up_proj",
                        target_module=RowW8A8BFP32OFP32Linear,
                        kwargs={"split_num": 1},
                    ),
                    SubModuleReplacementDescription(
                        suffix="mlp.down_proj",
                        target_module=ColW8A8BFP32OFP32Linear,
                        kwargs={"split_num": 1},
                    ),
                ],
            )
        self.shard_config._infer()

        infer_forward = llama_causal_lm_forward
        method_replacement = {"forward": partial(infer_forward)}
        self.append_or_create_method_replacement(
            description=method_replacement, policy=policy, target_key=LlamaForCausalLM
        )

        infer_forward = llama_model_forward
        method_replacement = {"forward": partial(infer_forward)}
        self.append_or_create_method_replacement(description=method_replacement, policy=policy, target_key=LlamaModel)

        infer_forward = llama_decoder_layer_forward
        method_replacement = {"forward": partial(infer_forward)}
        self.append_or_create_method_replacement(
            description=method_replacement, policy=policy, target_key=LlamaDecoderLayer
        )

        infer_forward = llama_attn_forward
        method_replacement = {"forward": partial(infer_forward)}
        self.append_or_create_method_replacement(
            description=method_replacement, policy=policy, target_key=LlamaAttention
        )

        infer_forward = llama_attn_forward
        method_replacement = {"forward": partial(infer_forward)}
        self.append_or_create_method_replacement(
            description=method_replacement, policy=policy, target_key=LlamaFlashAttention2
        )

        infer_forward = llama_attn_forward
        method_replacement = {"forward": partial(infer_forward)}
        self.append_or_create_method_replacement(
            description=method_replacement, policy=policy, target_key=LlamaSdpaAttention
        )

        return policy
