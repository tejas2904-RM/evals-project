"""The six deterministic graders."""

from evalpilot.graders.code.advice import ADVICE
from evalpilot.graders.code.citation import CITATION
from evalpilot.graders.code.fee_accuracy import FEE_ACCURACY
from evalpilot.graders.code.refusal import REFUSAL
from evalpilot.graders.code.unsafe_claim import UNSAFE_CLAIM
from evalpilot.graders.code.wrong_entity import WRONG_ENTITY

CODE_GRADERS = (REFUSAL, ADVICE, UNSAFE_CLAIM, CITATION, WRONG_ENTITY, FEE_ACCURACY)

__all__ = ["ADVICE", "CITATION", "CODE_GRADERS", "FEE_ACCURACY", "REFUSAL", "UNSAFE_CLAIM", "WRONG_ENTITY"]
