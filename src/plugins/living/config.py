import nonebot


configs = nonebot.get_driver().config

llm_cfg = configs.llm_config
setting_cfg = configs.setting_config
chat_cfg = configs.chat_config
scheduler_cfg = configs.scheduler_config