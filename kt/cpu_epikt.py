"""Load the original ALiBi model with CPU-only tensor allocation."""

from types import ModuleType

from kt.train import MODEL_SOURCE


def init_cpu_alibi(model_config: dict, data_config: dict):
    import torch

    # Adapt an isolated copy of the verified source. The training bundle and
    # checkpoint stay intact, and the original CUDA module remains available.
    source = MODEL_SOURCE.read_text(encoding="utf-8")
    allocations = (
        "torch.arange(maxpos)[:, None].cuda()",
        "torch.arange(maxpos)[None, :].cuda()",
        "torch.Tensor(get_slopes(attn_heads)).cuda()",
    )
    if any(source.count(expression) != 1 for expression in allocations):
        raise ValueError("The bundled EpiKT ALiBi allocations do not match the CPU adapter.")
    for expression in allocations:
        source = source.replace(expression, expression.removesuffix(".cuda()") + ".to(device)")

    model_code = ModuleType("_querystep_cpu_epikt")
    model_code.__file__ = str(MODEL_SOURCE)
    exec(compile(source, str(MODEL_SOURCE), "exec"), vars(model_code))
    model_code.device = torch.device("cpu")
    return model_code.EpiKT(
        data_config["num_c"], data_config["num_q"], **model_config,
        emb_type="qid_alibi", emb_path=data_config["emb_path"],
    ).to(model_code.device)
