import os
import io
import logging
import math
import database
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
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
        BotCommand("join", "Rejoindre la saison en cours"),
        BotCommand("scores", "Voir le classement"),
        BotCommand("play", "Enregistrer une manche"),
        BotCommand("donate", "Donation de points à un/des joueur(s)"),
        BotCommand("graph", "Graphique des scores"),
        BotCommand("graphtime", "Évolution des scores dans le temps"),
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
        "/join : Rejoindre la saison en cours\n"
        "/scores : Classement et cartes spéciales\n"
        "/graph : Voir l'évolution des scores de la saison\n"
        "/graphtime : Voir l'évolution des scores dans le temps\n"
        "/stats @joueur : Profil détaillé\n\n"
        "🎮 *Jouer une manche*\n"
        "/play +1 @Joueur2 -1 ... : Le premier score est le TIEN, puis liste les autres joueurs et leurs scores.\n\n"
        "🎁 *Donner des points*\n"
        "/donate @Joueur 3 : Donne 3 points à un joueur\n"
        "/donate 3 : Donne 3 points aléatoirement à 3 joueurs\n\n"
        "🔄 *Révolution*\n"
        "/revolution A : Change les cartes spéciales\n\n"
        "⚙️ *Admin*\n"
        "/newseason NomDeLaSaison : Termine la saison et en commence une nouvelle.\n"
        "/fix : Corrige les noms d'affichage (Admin)"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def join_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    author = update.effective_user
    author_username = author.username if author.username else f"no_uname_{author.id}"
    author_display_name = author.first_name.split(" ")[0]

    database.register_or_join_player(
        author.id,
        author_username,
        author_display_name,
    )
    await update.message.reply_text(f"✅ Bienvenue dans la ligue {author_display_name}!")

async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    author = update.effective_user

    if not args or len(args) % 2 == 0:
        await update.message.reply_text("❌ Usage: `/play <ton_score> @Joueur2 <score2> ...`", parse_mode="Markdown")
        return

    try:
        updates = {}
        updates[author.username] = int(args[0])

        for i in range(1, len(args), 2):
            username = args[i].replace('@', '')
            if username in updates:
                await update.message.reply_text(f"❌ Le joueur @{username} ne peut pas avoir plus que 1 score.")
                return
            score = int(args[i+1])
            updates[username] = score

        if sum(updates.values()) != 0:
            await update.message.reply_text(f"❌ Somme = {sum(updates.values())}. Elle doit être 0 !")
            return

        # Check all players exist in database
        players = database.get_all_player_usernames()
        for uname in updates:
            if uname not in players:
                await update.message.reply_text(f"❌ Le joueur @{uname} n'a pas rejoint la saison en cours.")
                return

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

    # Escape Markdown special characters in user-provided strings
    def escape_md(text):
        return str(text).replace('*', '\\*').replace('_', '\\_')

    name_escaped = escape_md(name)
    spec_escaped = [escape_md(s) for s in spec]

    text = f"🏆 *CLASSEMENT : {name_escaped}*\n"
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

            p_name_escaped = escape_md(p_name)
            text += f"{medal} {p_name_escaped} : *{score}*\n"

    text += "▬" * 12 + "\n"
    text += f"💥 Spéciales : *{spec_escaped[0]}* et *{spec_escaped[1]}*"

    await update.message.reply_text(text, parse_mode="Markdown")

async def graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = database.get_score_history()
    if not data:
        await update.message.reply_text("Pas assez de données pour générer un graphique.")
        return

    history = {}
    for name, x, change, event_type in data:
        history.setdefault(name, []).append((x, change, event_type))

    plot_colors = plt.cm.tab20(range(len(history)))
    plt.figure(figsize=(10, 6))

    max_round = 0
    for index, (name, events) in enumerate(history.items()):
        events.sort(key=lambda item: (item[0], 0 if item[2] == "round" else 1))
        xs = [0.0]
        ys = [0]
        current = 0
        donation_x = []
        donation_y = []
        event_index = 0

        max_round = math.ceil(max(x for x, _, _ in events)) if events else 0

        for round_number in range(1, max_round + 1):
            while event_index < len(events) and events[event_index][0] < round_number:
                x, change, event_type = events[event_index]
                current += change
                xs.append(x)
                ys.append(current)
                if event_type == "donation":
                    donation_x.append(x)
                    donation_y.append(current)
                event_index += 1

            while event_index < len(events) and events[event_index][0] == round_number:
                x, change, event_type = events[event_index]
                current += change
                xs.append(x)
                ys.append(current)
                if event_type == "donation":
                    donation_x.append(x)
                    donation_y.append(current)
                event_index += 1

            if xs[-1] != float(round_number):
                xs.append(float(round_number))
                ys.append(current)

        while event_index < len(events):
            x, change, event_type = events[event_index]
            current += change
            xs.append(x)
            ys.append(current)
            if event_type == "donation":
                donation_x.append(x)
                donation_y.append(current)
            event_index += 1

        plt.plot(xs, ys, marker='o', label=name, color=plot_colors[index % len(plot_colors)])

    ax = plt.gca()
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=8, prune='both'))
    plt.title("Évolution de la Saison")
    plt.xlabel("Manches")
    plt.ylabel("Points")
    plt.legend(loc='upper left', fontsize='small')
    plt.grid(True, linestyle='--')

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()

    await update.message.reply_photo(photo=buf, caption="📈 Évolution des scores")

async def graphtime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = database.get_score_history_timed()
    if not data:
        await update.message.reply_text("Pas assez de données pour générer un graphique temporel.")
        return

    history = {}
    for name, timestamp, change, event_type in data:
        if not timestamp:
            continue
        history.setdefault(name, []).append((timestamp, change, event_type))

    active_rows, _, _ = database.get_current_leaderboard()
    for name, _ in active_rows:
        history.setdefault(name, [])

    timestamps = sorted({timestamp for _, timestamp, _, _ in data if timestamp})
    if not timestamps:
        await update.message.reply_text("Pas assez de données pour générer un graphique temporel.")
        return

    plot_colors = plt.cm.tab20(range(len(history)))
    plt.figure(figsize=(10, 6))

    for index, (name, events) in enumerate(history.items()):
        changes_by_time = {}
        for timestamp, change, _ in events:
            changes_by_time[timestamp] = changes_by_time.get(timestamp, 0) + change

        xs = [timestamps[0]]
        ys = [0]
        current = 0
        for timestamp in timestamps:
            if xs[-1] != timestamp:
                xs.append(timestamp)
                ys.append(current)
            if timestamp in changes_by_time:
                current += changes_by_time[timestamp]
                xs.append(timestamp)
                ys.append(current)

        plt.plot(xs, ys, drawstyle='steps-post', marker='o', label=name, color=plot_colors[index % len(plot_colors)])

    ax = plt.gca()
    locator = mdates.AutoDateLocator()
    formatter = mdates.ConciseDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)

    plt.title("Évolution des scores dans le temps")
    plt.xlabel("Temps")
    plt.ylabel("Points")
    plt.legend(loc='upper left', fontsize='small')
    plt.grid(True, linestyle='--')

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()

    await update.message.reply_photo(photo=buf, caption="📈 Évolution des scores dans le temps")

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
    app.add_handler(CommandHandler("join", join_season))
    app.add_handler(CommandHandler("play", play))
    app.add_handler(CommandHandler("donate", donate))
    app.add_handler(CommandHandler("graph", graph))
    app.add_handler(CommandHandler("graphtime", graphtime))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("scores", leaderboard))
    app.add_handler(CommandHandler("revolution", revolution))
    app.add_handler(CommandHandler("newseason", new_season))

    print("Bot launched...")
    app.run_polling()