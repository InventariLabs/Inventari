from app.core.define_module import define_module
from app.core.public_api import core_api
from app.core.public_api.llm import LlmCapability
from app.modules.vision._probe import probe as vision_probe
from app.modules.vision.router import router

# Register vision's AI purpose at module-load time. The Core owns the
# connection pool + client factory; each feature declares the purpose
# it needs (here: ``vision.extract`` — pull structured data from an
# image of a stock item). The resolver in :mod:`app.core.llm.registry`
# looks this up at call time and binds it to whichever connection the
# org has marked as the default for VISION.
#
# The purpose ships with a contract probe so the connection test can ask the
# real question — "can this model read a label?" — instead of the easy one,
# "does this key work?".
core_api.llm.register_purpose(
    key='vision.extract',
    capability=LlmCapability.VISION,
    label_key='vision:ai.purposeLabel',
    description_key='vision:ai.purposeDesc',
    owner_module='vision',
    probe=vision_probe,
)

module = define_module(router=router)
