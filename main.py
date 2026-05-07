import os
import io
import logging
import database
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from telegram import Update, BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

database.init_db()

logging.basicConfig(level=logging.INFO)

async def post_init(application):
    commands = [
        BotCommand("help", "Affiche l'aide et les règles"),
        BotCommand("scores", "Voir le classement"),
        BotCommand("play", "Enregistrer une manche"),
        BotCommand("donate", "Donation de points à un/des joueur(s)"),
        BotCommand("graph", "Graphique des scores"),
        BotCommand("stats", "Stats d'un joueur"),
        BotCommand("revolution", "Lancer une révolution"),
        BotCommand("newseason", "Nouvelle saison (Admin)"),
    ]

    await application.bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
    await application.bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **Guide d'utilisation du Bot**\n\n"
        "👤 **Joueurs**\n"
        "/scores : Classement et cartes spéciales\n"
        "/graph : Voir l'évolution des scores de la saison\n"
        "/stats @joueur : Profil détaillé\n\n"
        "🎮 *Jouer une manche*\n"
        "/play +1 @Joueur2 -1 ... : Le premier score est le TIEN, puis liste les autres joueurs et leurs scores.\n\n"
        "🎁 *Donner des points*\n"
        "/donate @Joueur 3 : Donne 3 points à un joueur\n"
        "/donate 3 : Donne 3 points aléatoirement à 3 joueurs\n\n"
        "🔄 *Révolution*\n"
        "/revolution A : Change les cartes spéciales\n\n"
        "⚙️ *Admin*\n"
        "/newseason NomDeLaSaison : Termine la saison et en commence une nouvelle."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

def collect_tagged_user_info(update: Update):
    tagged = {}
    if not update.message or not update.message.entities:
        return tagged

    text = update.message.text or ""
    for entity in update.message.entities:
        if entity.type == "text_mention" and entity.user:
            username = entity.user.username if entity.user.username else f"no_uname_{entity.user.id}"
            tagged[username] = {
                "user_id": entity.user.id,
                "display_name": entity.user.first_name,
            }
        elif entity.type == "mention":
            mention_text = text[entity.offset:entity.offset + entity.length]
            username = mention_text.lstrip('@')
            if username not in tagged:
                tagged[username] = {
                    "user_id": None,
                    "display_name": username,
                }

    return tagged

async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    author = update.effective_user

    if not args or len(args) % 2 == 0:
        await update.message.reply_text("❌ Usage: `/play <ton_score> @Joueur2 <score2> ...`", parse_mode="Markdown")
        return

    try:
        updates = {}
        author_username = author.username if author.username else f"no_uname_{author.id}"
        author_display_name = author.first_name
        updates[author_username] = int(args[0])

        tagged_users = collect_tagged_user_info(update)
        tagged_users[author_username] = {
            "user_id": author.id,
            "display_name": author_display_name,
        }

        for i in range(1, len(args), 2):
            username = args[i].replace('@', '')
            score = int(args[i+1])
            updates[username] = score

        if sum(updates.values()) != 0:
            await update.message.reply_text(f"❌ Somme = {sum(updates.values())}. Elle doit être 0 !")
            return

        for username in updates:
            player_info = tagged_users.get(username)
            if player_info:
                database.ensure_player_for_season(
                    username,
                    user_id=player_info.get("user_id"),
                    display_name=player_info.get("display_name"),
                )
            else:
                database.ensure_player_for_season(username, display_name=username)

        error = database.add_round_scores(updates)
        if error:
            await update.message.reply_text(f"⚠️ {error}")
        else:
            await update.message.reply_text("📝 Manche enregistrée !")

    except ValueError:
        await update.message.reply_text("❌ Les scores doivent être des entiers.")

async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: `/donate @Joueur <points>` ou `/donate <points>`", parse_mode="Markdown")
        return

    try:
        if len(context.args) == 1:
            recipient = None
            amount = int(context.args[0])
        elif len(context.args) == 2 and context.args[0].startswith("@"):
            recipient = context.args[0].lstrip('@')
            amount = int(context.args[1])
        else:
            await update.message.reply_text("❌ Usage: `/donate @Joueur <points>` ou `/donate <points>`", parse_mode="Markdown")
            return
    except ValueError:
        await update.message.reply_text("❌ Les points doivent être un entier.")
        return

    author = update.effective_user
    donor_username = author.username if author.username else f"no_uname_{author.id}"

    if recipient:
        error = database.donate_to_player(donor_username, recipient, amount)
        if error:
            await update.message.reply_text(f"⚠️ {error}")
        else:
            await update.message.reply_text(f"🎁 Tu as donné {amount} points à @{recipient} !")
    else:
        error, summary = database.donate_random(donor_username, amount)
        if error:
            await update.message.reply_text(f"⚠️ {error}")
            return

        lines = [f"🎲 Don aléatoire : {amount} point(s) distribués"]
        for name, count in summary.items():
            lines.append(f"• {name} +{count}")
        await update.message.reply_text("\n".join(lines))

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows, name, spec = database.get_current_leaderboard()

    text = f"🏆 *CLASSEMENT : {name}*\n"
    text += "▬" * 12 + "\n"

    if not rows:
        text += "Aucun score pour le moment.\n"
    else:
        for i, (p_name, score) in enumerate(rows, 1):
            if i == 1:
                medal = "🥇"
            elif i == len(rows) and len(rows) > 1:
                medal = "🌯"
            else:
                medal = "🔹"

            text += f"{medal} {p_name} : *{score}*\n"

    text += "▬" * 12 + "\n"
    text += f"💥 Spéciales : *{spec[0]}* et *{spec[1]}*"

    await update.message.reply_text(text, parse_mode="Markdown")

async def graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = database.get_score_history()
    if not data:
        await update.message.reply_text("Pas assez de données pour générer un graphique.")
        return

    history = {}
    rounds = sorted(list(set(d[1] for d in data)))

    for name, round_num, change in data:
        if name not in history:
            history[name] = [0] * (max(rounds) + 1)
        history[name][round_num] = change

    plt.figure(figsize=(10, 6))
    colors = plt.cm.tab20(range(len(history)))
    for (name, scores), color in zip(history.items(), colors):
        cumulative = []
        current = 0
        for s in scores[1:]:
            current += s
            cumulative.append(current)
        plt.plot(rounds, cumulative, marker='o', label=name, color=color)

    plt.title("Évolution de la Saison")
    plt.xlabel("Manches")
    plt.ylabel("Points")
    plt.legend(loc='upper left')
    plt.grid(True, linestyle='--')

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()

    await update.message.reply_photo(photo=buf, caption="📈 Évolution des scores")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = None
    if context.args:
        target = context.args[0]
    else:
        author = update.effective_user
        target = author.username if author.username else f"no_uname_{author.id}"

    res = database.get_player_stats(target)
    if not res:
        await update.message.reply_text("❌ Joueur introuvable dans la base de données.")
        return

    sep = "▬" * 12

    lines = [
        f"👤 *PROFIL DE {res['name'].upper()}*",
        sep,
        "📊 *Activité*",
        f"• Manches jouées : {res['nb_manches']}",
        f"• Score moyen : `{res['avg_score']}`",
        "",
        "⚔️ *Relations*",
        f"• Partenaire de jeu : {res['most_played']}",
        f"• Sa victime : {res['victim']}",
        f"• Son bourreau : {res['nemesis']}",
        sep
    ]

    msg = "\n".join(lines)

    await update.message.reply_text(msg, parse_mode="Markdown")

async def revolution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: `/revolution <carte>`")
        return

    new_card = context.args[0].upper()
    if database.apply_revolution(new_card):
        _, _, s = database.get_current_leaderboard()
        await update.message.reply_text(f"🔄 **RÉVOLUTION !**\nNouvelles spéciales : {s[0]} {s[1]}", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Aucune saison active.")

async def new_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        await update.message.reply_text("🚫 Admin uniquement.")
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: `/newseason Nom`")
        return

    name = " ".join(context.args)
    prev_stats = database.start_new_season(name)

    msg = f"🌟 **NOUVELLE SAISON : {name}** 🌟\nSpéciales par défaut : J Q"
    if prev_stats:
        msg += f"\n\n🏁 **Saison précédente :**\n🥇 {prev_stats[0][0]} ({prev_stats[0][1]})\n🌯 {prev_stats[-1][0]} ({prev_stats[-1][1]})"

    await update.message.reply_text(msg, parse_mode="Markdown")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("play", play))
    app.add_handler(CommandHandler("donate", donate))
    app.add_handler(CommandHandler("graph", graph))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("scores", leaderboard))
    app.add_handler(CommandHandler("revolution", revolution))
    app.add_handler(CommandHandler("newseason", new_season))

    print("Bot launched...")
    app.run_polling()