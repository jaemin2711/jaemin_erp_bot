from bot_config import *
from bot_config import (
    _improved_whoami_command,
    _improved_status_command,
    _improved_backup_command,
    _improved_logs_command,
    _improved_global_error_handler,
)

from core_handlers import (
    start_command,
    id_command,
    register_command,
    version_command,
    handle_message,
    handle_callback,
)

from plan_reports import (
    production_help_command,
    menu_command,
    history_command,
    risk_command,
    riskweek_command,
    riskmonth_command,
    today_command,
    tomorrow_command,
    week_command,
    calendar_command,
)

from product_alias_ocr import (
    product_command,
    aliasadd_command,
    aliaslist_command,
    aliasdel_command,
    ocrmemory_command,
)

from reserved_contract import (
    contract_command,
    plan_natural_change_command,
    reserved_plan_command,
)

from plan_commands import (
    planlist_command,
    plans_command,
    editplan_command,
    delplan_command,
)

from force_plan import (
    forceplan_command,
    force_mode_command,
)

from image_handlers import handle_photo


def build_application():
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(4)
        .connect_timeout(30)
        .read_timeout(120)
        .write_timeout(120)
        .pool_timeout(120)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", production_help_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("risk", risk_command))
    app.add_handler(CommandHandler("riskweek", riskweek_command))
    app.add_handler(CommandHandler("riskmonth", riskmonth_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("tomorrow", tomorrow_command))
    app.add_handler(CommandHandler("week", week_command))
    app.add_handler(CommandHandler("calendar", calendar_command))
    app.add_handler(CommandHandler("product", product_command))
    app.add_handler(CommandHandler("aliasadd", aliasadd_command))
    app.add_handler(CommandHandler("aliasset", aliasadd_command))
    app.add_handler(CommandHandler("aliaslist", aliaslist_command))
    app.add_handler(CommandHandler("aliasdel", aliasdel_command))
    app.add_handler(CommandHandler("aliasdelete", aliasdel_command))
    app.add_handler(CommandHandler("aliasforget", aliasdel_command))
    app.add_handler(CommandHandler("contractadd", contract_command))
    app.add_handler(CommandHandler("contractlist", contract_command))
    app.add_handler(CommandHandler("contractcheck", contract_command))
    app.add_handler(CommandHandler("contractdel", contract_command))
    app.add_handler(CommandHandler("contractplan", contract_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("register", register_command))
    app.add_handler(CommandHandler("version", version_command))
    app.add_handler(CommandHandler("ocrmemory", ocrmemory_command))
    app.add_handler(CommandHandler("ocradd", ocrmemory_command))
    app.add_handler(CommandHandler("ocrset", ocrmemory_command))
    app.add_handler(CommandHandler("ocrforget", ocrmemory_command))
    app.add_handler(CommandHandler("planlist", planlist_command))
    app.add_handler(CommandHandler("changeplan", plan_natural_change_command))
    app.add_handler(CommandHandler("reserveplan", reserved_plan_command))
    app.add_handler(CommandHandler("reservedplans", reserved_plan_command))
    app.add_handler(CommandHandler("reservedel", reserved_plan_command))
    app.add_handler(CommandHandler("reserveddelete", reserved_plan_command))
    app.add_handler(CommandHandler("reserveactual", reserved_plan_command))
    app.add_handler(CommandHandler("reservedactual", reserved_plan_command))
    app.add_handler(CommandHandler("plans", plans_command))
    app.add_handler(CommandHandler("plan", plans_command))
    app.add_handler(CommandHandler("editplan", editplan_command))
    app.add_handler(CommandHandler("delplan", delplan_command))
    app.add_handler(CommandHandler("forceplan", forceplan_command))
    app.add_handler(CommandHandler("forcemode", force_mode_command))
    app.add_handler(CommandHandler("forcestatus", force_mode_command))
    app.add_handler(CommandHandler("forceon", force_mode_command))
    app.add_handler(CommandHandler("forceoff", force_mode_command))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))

    if _improved_whoami_command:
        app.add_handler(CommandHandler("whoami", _improved_whoami_command))
    if _improved_status_command:
        app.add_handler(CommandHandler("status", _improved_status_command))
    if _improved_backup_command:
        app.add_handler(CommandHandler("backup", _improved_backup_command))
    if _improved_logs_command:
        app.add_handler(CommandHandler("logs", _improved_logs_command))
    if _improved_global_error_handler:
        app.add_error_handler(_improved_global_error_handler)

    return app
