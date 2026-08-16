import asyncio
import logging
import sqlite3
import math
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BotCommand 


from config import BOT_TOKEN, DB_NAME
from database import (
    init_db, register_chat, get_chat_settings,
    add_candidate, get_candidates, clear_candidates,
    set_election_state, get_election_state, update_chat_threshold,
    update_chat_quorum, update_chat_duration, save_config_poll
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start для проверки доступности бота"""
    register_chat(message.chat.id)
    await message.answer(
        "Привет! Я бот ОГАС.\n"
        "Используйте команду /help_ogas для показа дочтупных команд."
    )

@dp.message(Command("help_ogas"))
async def cmd_help_ogas(message: types.Message):
    """Выводит список всех доступных команд бота с описанием и ссылкой на код"""
    help_text = (
        "ℹ️ **Выборы администраторов:**\n"
        "🔹 `/start_election` — Начать сбор заявок от кандидатов в админы.\n"
        "🔹 `Иду на выборы` — Текст-заявка (отправлять строго ответом (**Reply**) на сообщение бота о старте выборов).\n"
        "🔹 `/finish_registration` — Закрыть сбор заявок и запустить общий опрос.\n"
        "🔹 `/stop_voting` — Досрочно закрыть опрос выборов (отправлять ответом (**Reply**) на сам опрос).\n\n"
        "📉 **Разжалование администраторов:**\n"
        "🔹 `/vote_demote` — Запустить голосование за снятие админа (отправлять ответом (**Reply**) на любое сообщение этого админа).\n\n"
        "⚙️ **Изменение настроек чата:**\n"
        "🔹 `/set_threshold [1-100]` — Запустить голосование за новый порог голосов для кандидатов.\n"
        "🔹 `/set_quorum [1-100]` — Запустить голосование за новый порог явки (% от участников).\n"
        "🔹 `/set_duration [1-168]` — Запустить голосование за новое время опросов (в часах).\n"
        "🔹 `/stop_config` — Досрочно закрыть опрос настроек (отправлять ответом (**Reply**) на опрос настроек).\n\n"
        "**Обратная связь и предложения по разработке: ** @groxconsul\n\n"
        "📌 _Примечание: В базовых настройках минимальная явка составляет 15% от участников чата, а порог прохождения на выборах администраторов 30%, время проведения опросов 24 часа._"
    )
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="📁 Репозиторий проекта ОГАС: ", url="https://github.com/MaksimDGood/OGAS")
    
    await message.answer(help_text, parse_mode="Markdown", reply_markup=builder.as_markup())


@dp.message(Command("vote_demote"))
async def cmd_vote_demote(message: types.Message):
    """Запускает опрос за лишение прав администратора через Reply на его сообщение"""
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Эту команду можно использовать только в группах!")
        return

    if not message.reply_to_message:
        await message.answer("⚠️ Сделайте ОТВЕТ (Reply) этой командой на сообщение администратора, которого хотите снять!")
        return

    target_user = message.reply_to_message.from_user
    chat_id = message.chat.id
    register_chat(chat_id)

    state = get_election_state(chat_id)
    if state and state["status"] in ["registration", "voting", "voting_promote", "voting_demote"]:
        await message.answer("❌ В чате уже идет избирательный процесс или сбор заявок. Подождите его окончания!")
        return

    settings = get_chat_settings(chat_id)
    duration_hours = settings.get("duration", 24)
    open_period_seconds = duration_hours * 3600

    options = ["Снять ❌", "Оставить как есть 🛡️"]

    poll_msg = await message.answer_poll(
        question=f"🗳️ РАЗЖАЛОВАНИЕ: Лишить {target_user.first_name} прав администратора?",
        options=options,
        is_anonymous=False,
        allows_multiple_answers=False, 
        type="regular",
        open_period=open_period_seconds
    )

    set_election_state(chat_id, status="voting_demote", poll_id=poll_msg.poll.id, msg_id=target_user.id)
    await message.answer(f"📢 Запущено голосование за снятие администратора на {duration_hours} ч.")

@dp.message(Command("start_election"))
async def cmd_start_election(message: types.Message):
    """Команда запускает сбор заявок кандидатов на выборы администратора"""
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Выборы можно проводить только в группах!")
        return

    chat_id = message.chat.id
    register_chat(chat_id)
    clear_candidates(chat_id)

    msg = await message.answer(
        "📢 **Внимание! Объявляется старт сбора заявок на выборы администратора!**\n\n"
        "Если вы хотите выдвинуть свою кандидатуру, отправьте ответ (**Reply**) "
        "на ЭТО сообщение с текстом: `Иду на выборы`.\n\n"
        "⏱ После сбора заявок используйте команду /finish_registration для запуска опроса."
    )
    
    set_election_state(chat_id, status="registration", msg_id=msg.message_id)
    print(f"[БАЗА ДАННЫХ] В чате {chat_id} запущен статус 'registration'")

@dp.message(Command("finish_registration"))
async def cmd_finish_registration(message: types.Message):
    """Закрывает сбор заявок и выводит в чат опрос с мультивыбором"""
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Эту команду можно использовать только в группах!")
        return

    chat_id = message.chat.id
    state = get_election_state(chat_id)

    if not state or state["status"] != "registration":
        await message.answer("В этом чате сейчас не запущен сбор заявок на выборы!")
        return

    candidates_list = get_candidates(chat_id)

    if not candidates_list:
        await message.answer("❌ Ни один кандидат не зарегистрировался. Выборы отменяются.")
        clear_candidates(chat_id)
        return

    options = []
    for c in candidates_list[:10]: # Ограничение Telegram API на 10 вариантов
        options.append(f"За {c['first_name']}")

    settings = get_chat_settings(chat_id)
    duration_hours = settings.get("duration", 24)
    open_period_seconds = duration_hours * 3600

    poll_msg = await message.answer_poll(
        question="🗳️ ГОЛОСОВАНИЕ ЗА АДМИНИСТРАТОРОВ! (Выберите кандидатов)",
        options=options,
        is_anonymous=False,
        allows_multiple_answers=True,
        type="regular",
        open_period=open_period_seconds
    )

    set_election_state(chat_id, status="voting", poll_id=poll_msg.poll.id, msg_id=poll_msg.message_id)
    await message.answer(f"📥 Прием заявок закрыт! Опрос выше запущен на {duration_hours} час(ов).")
    print(f"[БАЗА ДАННЫХ] Чат {chat_id} переведен в режим 'voting'.")

@dp.message(Command("stop_voting"))
async def cmd_stop_voting(message: types.Message):
    """Позволяет досрочно закрыть опрос выборов через Reply и подвести итоги"""
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Эту команду можно использовать только в группах!")
        return

    chat_id = message.chat.id
    state = get_election_state(chat_id)

    if not state or state["status"] not in ["voting", "voting_demote"]:
        await message.answer("В этом чате сейчас не запущено активное голосование за администраторов!")
        return


    poll_msg_id = message.reply_to_message.message_id if message.reply_to_message else state["msg_id"]

    try:
        final_poll = await bot.stop_poll(chat_id=chat_id, message_id=poll_msg_id)
    except Exception as err:
        await message.answer(f"⚠️ Ошибка закрытия опроса. Сделайте REPLY командой `/stop_voting` на сам опрос! Ошибка: `{err}`")
        return

    await handle_poll_closed(final_poll)

async def start_config_vote(message: types.Message, config_type: str, new_value: int, question_text: str):
    chat_id = message.chat.id
    register_chat(chat_id)

    poll_msg = await message.answer_poll(
        question=question_text,
        options=["За 👍", "Против 👎"],
        is_anonymous=False,
        type="regular",
        open_period=86400  # 24 часа
    )

    save_config_poll(poll_msg.poll.id, chat_id, config_type, new_value)
    await message.answer(f"🗳️ Запущено официальное голосование большинства за изменение параметров чата на 24 часа.")


@dp.message(Command("set_threshold"))
async def cmd_set_threshold(message: types.Message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: `/set_threshold [число от 1 до 100]`")
        return
    val = int(args[1])
    await start_config_vote(message, "threshold", val, f"🗳️ Изменить порог прохождения для кандидатов в админы на {val}%?")


@dp.message(Command("set_quorum"))
async def cmd_set_quorum(message: types.Message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: `/set_quorum [число от 1 до 100]`")
        return
    val = int(args[1])
    await start_config_vote(message, "quorum", val, f"🗳️ Изменить минимальный порог явки на выборах на {val}% от участников?")


@dp.message(Command("set_duration"))
async def cmd_set_duration(message: types.Message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: `/set_duration [время в часах от 1 до 168]`")
        return
    val = int(args[1])
    await start_config_vote(message, "duration", val, f"🗳️ Изменить время проведения выборов на {val} час(ов)?")

@dp.message(Command("stop_config"))
async def cmd_stop_config(message: types.Message):
    """Позволяет досрочно закрыть опрос настроек через Reply и применить итоги"""
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Эту команду можно использовать только в группах!")
        return

    if not message.reply_to_message or not message.reply_to_message.poll:
        await message.answer("⚠️ Сделайте ОТВЕТ (Reply) командой `/stop_config` прямо на опрос настроек!")
        return

    chat_id = message.chat.id
    poll_id = message.reply_to_message.poll.id

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id, config_type, new_value FROM config_polls WHERE poll_id = ?', (poll_id,))
    config_row = cursor.fetchone()
    conn.close()

    if not config_row:
        await message.answer("Этот опрос не найден в базе данных настроек или уже был закрыт.")
        return

    try:
        final_poll = await bot.stop_poll(chat_id=chat_id, message_id=message.reply_to_message.message_id)
        print(f"[УСПЕХ] Технический опрос {poll_id} успешно остановлен вручную.")
    except Exception as err:
        await message.answer(f"⚠️ Не удалось закрыть опрос через API. Ошибка: `{err}`")
        return

    await handle_poll_closed(final_poll)

@dp.poll()
async def handle_poll_closed(poll: types.Poll):
    """Перехватывает закрытие любых опросов (по таймеру или вручную) и считает голоса"""
    if not poll.is_closed:
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id, config_type, new_value FROM config_polls WHERE poll_id = ?', (poll.id,))
    config_row = cursor.fetchone()
    cursor.execute('SELECT chat_id FROM election_state WHERE poll_id = ?', (poll.id,))
    election_row = cursor.fetchone()
    conn.close()

    if not config_row and not election_row:
        return 

    chat_id = config_row[0] if config_row else election_row[0]
    settings = get_chat_settings(chat_id)
    
    current_quorum_percent = settings.get("quorum_percent", 15)
    current_threshold_percent = settings.get("threshold", 30)

    try:
        total_members = await bot.get_chat_member_count(chat_id)
    except Exception:
        total_members = 100
        
    required_quorum_voters = math.ceil((total_members * current_quorum_percent) / 100)
    total_voters = poll.total_voter_count

    if total_voters < required_quorum_voters:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ **Голосование автоматически завершено, но признано несостоявшимся из-за низкой явки!**\n\n"
                 f"Для легитимности требовалось участие {current_quorum_percent}% чата: **{required_quorum_voters}** чел.\n"
                 f"Фактически проголосовало: **{total_voters}** чел. Решение/выборы аннулированы."
        )
        if election_row:
            clear_candidates(chat_id)
        return

    if config_row:
        _, c_type, new_val = config_row
        votes_yes = poll.options[0].voter_count  # За 
        votes_no = poll.options[1].voter_count   # Против 

        if votes_yes > votes_no:
            if c_type == "threshold":
                update_chat_threshold(chat_id, new_val)
                await bot.send_message(chat_id=chat_id, text=f"✅ **Решение принято большинством!**\nПорог прохождения кандидатов изменен на **{new_val}%**.")
            elif c_type == "quorum":
                update_chat_quorum(chat_id, new_val)
                await bot.send_message(chat_id=chat_id, text=f"✅ **Решение принято большинством!**\nМинимальный порог явки изменен на **{new_val}%**.")
            elif c_type == "duration":
                update_chat_duration(chat_id, new_val)
                await bot.send_message(chat_id=chat_id, text=f"✅ **Решение принято большинством!**\nВремя проведения голосования изменено на **{new_val}** ч.")
        else:
            await bot.send_message(chat_id=chat_id, text=f"❌ **Предложение отклонено!** Большинство проголосовало против (ЗА: {votes_yes}, ПРОТИВ: {votes_no}).")
            
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM config_polls WHERE poll_id = ?', (poll.id,))
        conn.commit()
        conn.close()

    elif election_row:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT status, announcement_msg_id FROM election_state WHERE chat_id = ?', (chat_id,))
        db_state = cursor.fetchone()
        conn.close()
        
        current_status = db_state[0] if db_state else "voting"
        target_admin_id = db_state[1] if db_state else None # Для снятия тут хранится user_id админа

        if current_status == "voting_demote" and target_admin_id:
            votes_demote = poll.options[0].voter_count  # Вариант "Снять ❌"
            votes_keep = poll.options[1].voter_count    # Вариант "Оставить 🛡️"
            
            # Высчитываем процент за снятие от всех проголосовавших человек
            demote_percent = (votes_demote / total_voters) * 100 if total_voters > 0 else 0
            
            await bot.send_message(
                chat_id=chat_id,
                text=f"📊 **ГОЛОСОВАНИЕ ЗА СНЯТИЕ АДМИНИСТРАТОРА ЗАВЕРШЕНО!**\n\n"
                     f"Явка пройдена! Всего голосов: {total_voters}\n"
                     f"Результат за снятие: {votes_demote} гол. ({demote_percent:.1f}%)\n"
                     f"Требуемый порог для снятия: {current_threshold_percent}%"
            )

            if demote_percent >= current_threshold_percent:
                try:
                    await bot.promote_chat_member(
                        chat_id=chat_id,
                        user_id=target_admin_id,
                        can_manage_chat=False, can_change_info=False, can_post_messages=False,
                        can_edit_messages=False, can_delete_messages=False, can_restrict_members=False,
                        can_invite_users=False, can_pin_messages=False, can_manage_video_chats=False,
                        is_anonymous=False, can_promote_members=False
                    )
                    await bot.send_message(chat_id=chat_id, text="📉 **Администратор успешно лишен всех полномочий по решению чата!**")
                except Exception as e:
                    await bot.send_message(chat_id=chat_id, text=f"⚠️ Ошибка: У бота нет прав разжаловать этого пользователя. Возможно, он создатель группы. Ошибка: {e}")
            else:
                await bot.send_message(chat_id=chat_id, text="🛡️ Администратор сохраняет свой пост, так как порог голосов за снятие не был достигнут.")
            
            clear_candidates(chat_id)

        else:
            candidates_list = get_candidates(chat_id)
            results_text = f"📊 **ГОЛОСОВАНИЕ ЗАВЕРШЕНО!**\nЯвка пройдена! Всего голосов: {total_voters}\nПорог прохождения кандидата: {current_threshold_percent}%\n\n"
            promoted_users = []

            for i, candidate in enumerate(candidates_list[:10]):
                if i >= len(poll.options): break
                votes_for_candidate = poll.options[i].voter_count
                percent = (votes_for_candidate / total_voters) * 100
                results_text += f"▪️ {candidate.get('first_name')}: {votes_for_candidate} гол. ({percent:.1f}%)\n"
                if percent >= current_threshold_percent:
                    promoted_users.append(candidate)

            await bot.send_message(chat_id=chat_id, text=results_text)

            if promoted_users:
                success_mentions = []
                for candidate in promoted_users:
                    try:
                        await bot.promote_chat_member(
                            chat_id=chat_id, user_id=candidate.get('user_id'),
                            can_manage_chat=True, can_change_info=True, can_post_messages=True,
                            can_edit_messages=True, can_delete_messages=True, can_restrict_members=True,
                            can_invite_users=True, can_pin_messages=True, can_manage_video_chats=True,
                            is_anonymous=False, can_promote_members=False
                        )
                        success_mentions.append(candidate.get('first_name'))
                    except Exception:
                        await bot.send_message(chat_id=chat_id, text=f"⚠️ Ошибка при назначении {candidate.get('first_name')}: У бота нет прав.")
                if success_mentions:
                    await bot.send_message(chat_id=chat_id, text=f"🎉 Новые администраторы успешно назначены: {', '.join(success_mentions)}!")
            else:
                await bot.send_message(chat_id=chat_id, text="Никто из кандидатов не набрал необходимый порог. Никто не назначен.")

            clear_candidates(chat_id)


@dp.message()
async def handle_candidate_registration(message: types.Message):
    """Строгий перехват фраз 'иду на выборы' в ответ на объявление бота"""
    if not message.text or message.text.startswith("/"):
        return

    chat_id = message.chat.id
    state = get_election_state(chat_id)
    
    if not state or state["status"] != "registration":
        return

    if not message.reply_to_message or message.reply_to_message.message_id != state["msg_id"]:
        return

    text = message.text.strip().lower()
    
    if text == "иду на выборы":
        user = message.from_user
        
        success = add_candidate(chat_id, user.id, user.username, user.first_name)
        
        if success:
            await message.reply(f"✅ Кандидатура {user.first_name} успешно зарегистрирована!")
            print(f"[УСПЕХ] Кандидат {user.first_name} записан в базу.")
        else:
            await message.reply("Вы уже добавлены в список кандидатов!")


async def main():
    """Главная функция инициализации, настройки меню и старта бота"""
    # 1. Создаем таблицы базы данных при старте, если их нет
    init_db()
    
    # 2. Формируем список команд для встроенного меню Telegram
    # (Слева пишется команда без слэша, справа — её понятное описание)
    main_commands = [
        BotCommand(command="help_ogas", description="📜 Показать все команды ОГАС"),
        BotCommand(command="start_election", description="📢 Начать выборы (Сбор заявок кандидатов)"),
        BotCommand(command="finish_registration", description="🗳️ Закрыть сбор заявок и запустить опрос"),
        BotCommand(command="stop_voting", description="⏱️ Досрочно закрыть выборы и подвести итоги"),
        BotCommand(command="vote_demote", description="📉 Запустить голосование за снятие админа"),
        BotCommand(command="set_threshold", description="⚙️ Голосование: новый порог для кандидатов (%)"),
        BotCommand(command="set_quorum", description="⚙️ Голосование: новый порог явки (%)"),
        BotCommand(command="set_duration", description="⚙️ Голосование: новое время опросов (ч)"),
        BotCommand(command="stop_config", description="🛠️ Досрочно закрыть опрос настроек чата")
    ]
    
    # Отправляем список команд в Telegram API, чтобы они появились в интерфейсе
    try:
        await bot.set_my_commands(main_commands)
        print("[СИСТЕМА] Меню команд успешно зарегистрировано в Telegram!")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось настроить меню команд: {e}")
    
    # 3. Запускаем чтение сообщений
    print("Бот успешно запущен и готов к работе!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
