import json
import nonebot
import sys
from nonebot.adapters.onebot.v11.adapter import Adapter as ONEBOT_V11Adapter
from nonebot.log import logger, default_filter
from nonebot.plugin import _managers
from nonebot.plugin.manager import PluginManager
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from typing import Any


def logo_startup(version: str) -> None:
    console = Console()
    console.clear()
    logo = r"""
 _____    ______     ___  ______     ____        
/_____/\ /_____/\   /__/\/_____/\   /___/\       
\:::_:\ \\::::_\/_  \::\/\:::_ \ \  \_::\ \      
    _\:\| \:\/___/\  ___  \:\ \ \ \   \::\ \     
   /::_/__ \_::._\:\/__/\  \:\ \ \ \  _\: \ \__  
   \:\____/\/_____\/\::\/   \:\_\ \ \/__\: \__/\ 
    \_____\/\_____/          \_____\/\________\/ 
                                                 
    """
    logo_text = Text(logo, style="#884499")
    info_text = Text.assemble(
        ("\n>_ After 25:00, keeps living.\n", "#884499"),
        (f">_ Version    : {version}\n", "#bb6688"),
        (f">_ Client Env : prod\n", "#8888cc"),
        (">_ Status     : Initializing...\n", "#ccaa88"),
        (">_ Powered by Nonebot2, Developed by Caffeine-co", "#ddaacc")
    )
    logo_text.append_text(info_text)
    panel = Panel(
        Align.center(logo_text),
        border_style="#ffffff",
        expand=False,
    )
    console.print(panel)

def init_log() -> None:
    logger.remove()
    custom_format: str = (
        "[<fg #39c5bb>{time:MM-DD HH:mm:ss}</fg #39c5bb>] "
        "[<fg #884499>25:01</fg #884499>] "
        "| <lvl>{level}</lvl> | "
        "{message}"
    )
    logger.add(
        sys.stdout,
        level=0,
        diagnose=False,
        filter=default_filter,
        format=custom_format,
    )

def get_configs() -> dict[str, Any]:
    try:
        with open("configs.json", "r", encoding="utf-8") as f:
            configs: dict = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load configs: {e}")
        input("Press Enter to quit...")
        sys.exit(1)
    return configs

def import_living_plugin() -> None:
    manager = PluginManager(["src.plugins.placeholder"])
    _managers.append(manager)
    import src.plugins.living

if __name__ == "__main__":
    ver = "v-dev"

    init_log()
    logo_startup(ver)
    extra_configs = get_configs()

    nonebot.init(
        version=ver,
        driver="~fastapi",
        localstore_use_cwd=True,
        command_start={"/"},
        command_sep={" "},
        **extra_configs
    )
    driver = nonebot.get_driver()
    driver.register_adapter(ONEBOT_V11Adapter)

    import_living_plugin()

    nonebot.run()