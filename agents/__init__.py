from .action_agent import ActionAgent
from .bm_agent import BmAgent
from .im_agent import ImAgent
from .plan_agent import PlanAgent
from .single_agent import SingleAgent

try:
    from .rag_agent import RagAgent
except ModuleNotFoundError as exc:
    if exc.name != "requests":
        raise

    class RagAgent:
        def __init__(self, *args, **kwargs):
            raise ModuleNotFoundError("RagAgent requires the `requests` package.")
