from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, emit, join_room
import random
import logging
import os
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory storage for game state
games = {}
questions = []

# Setup logging directory
LOG_DIR = 'logs'
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def get_logger(game_code):
    logger = logging.getLogger(game_code)
    if not logger.handlers:
        log_file = os.path.join(LOG_DIR, f"game_{game_code}.log")
        handler = logging.FileHandler(log_file)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

# Load questions from questions.txt
with open('questions.txt', 'r') as f:
    questions = [line.strip() for line in f if line.strip()]

def get_random_question():
    return random.choice(questions)

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            game_code = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890", k=6))
            while game_code in games:  # Ensure unique code
                game_code = ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890", k=6))
            games[game_code] = {
                'players': [],
                'points': {},
                'judge_index': 0,
                'friends': [],
                'targeted_player': '',
                'current_question': '',
                'selected_friend': '',
                'judge_guess': ''
            }
            logger = get_logger(game_code)
            logger.info(f"Game created with code {game_code}")
            return redirect(url_for('lobby', code=game_code))
        elif action == 'join':
            code = request.form.get('code')
            if code in games:
                return redirect(url_for('lobby', code=code))
            else:
                return "<h3>Game code not found!</h3>", 404
    return render_template('home.html')

@app.route('/lobby/<code>')
def lobby(code):
    if code not in games:
        return "<h3>Game not found!</h3>", 404
    return render_template('lobby.html', code=code, players=games[code]['players'])

@app.route('/setup/<code>')
def setup(code):
    if code not in games:
        return "<h3>Game not found!</h3>", 404
    return render_template('setup.html', code=code)

@app.route('/round_start/<code>')
def round_start(code):
    if code not in games:
        return "<h3>Game not found!</h3>", 404
    game = games[code]
    judge = game['players'][game['judge_index']]
    if len(game['players']) == 2:  # Auto-assign target and navigate to gameplay for 2 players
        game['targeted_player'] = game['players'][1 - game['judge_index']]
        return redirect(url_for('gameplay', code=code))
    return render_template(
        'roundstart.html', code=code, judge=judge, question=get_random_question(), players=game['players']
    )

@app.route('/gameplay/<code>')
def gameplay(code):
    if code not in games:
        return "<h3>Game not found!</h3>", 404

    game = games[code]
    players = game['players']
    judge_index = game['judge_index']

    # Dynamically determine the targeted player based on judge_index
    targeted_player = players[1 - judge_index] if len(players) == 2 else game.get('targeted_player')

    # Ensure a new question is generated
    game['current_question'] = get_random_question()

    return render_template(
        'gameplay.html',
        code=code,
        targeted_player=targeted_player,
        question=game['current_question'],
        friends=game['friends'],
        scores=game['points']
    )


@app.route('/judge_guess/<code>')
def judge_guess(code):
    if code not in games:
        return "<h3>Game not found!</h3>", 404
    game = games[code]
    judge = game['players'][game['judge_index']]
    return render_template(
        'judge_guess.html',
        code=code,
        judge=judge,
        targeted_player=game['targeted_player'],
        friends=game['friends'],
        scores=game['points']
    )

# Socket.IO Logic
@socketio.on('join')
def handle_join(data):
    room = data['room']
    if room in games:
        join_room(room)
        logger = get_logger(room)
        logger.info(f"User joined room {room}")
        emit('update_players', {'players': games[room]['players']}, room=room)

@socketio.on('add_player')
def handle_add_player(data):
    room = data['room']
    name = data['name']
    logger = get_logger(room)
    if room in games and name not in games[room]['players']:
        games[room]['players'].append(name)
        games[room]['points'][name] = 0
        join_room(room)
        emit('update_players', {'players': games[room]['players']}, room=room)
        logger.info(f"Player {name} added to room {room}.")
        for handler in logger.handlers:
            handler.flush()
    else:
        emit('error', {'message': 'Name already taken or room not found.'})

@socketio.on('submit_friends')
def handle_submit_friends(data):
    room = data['room']
    friends = data['friends']
    logger = get_logger(room)
    if room in games and len(friends) == 5:  # Ensure exactly 5 friends are submitted
        games[room]['friends'] = friends
        emit('navigate_to_round_start', {'room': room}, room=room)
        logger.info(f"Friends list submitted in room {room}: {friends}")
        for handler in logger.handlers:
            handler.flush()
    else:
        emit('error', {'message': 'Invalid friends list.'})


@socketio.on('begin_game')
def handle_begin_game(data):
    room = data['room']
    logger = get_logger(room)
    if room in games and len(games[room]['players']) >= 2:
        emit('navigate_to_setup', {'room': room}, room=room)
        logger.info(f"Game started in room {room}")
        for handler in logger.handlers:
            handler.flush()
    else:
        emit('error', {'message': 'Not enough players to start the game.'})

@socketio.on('friend_selected')
def handle_friend_selected(data):
    room = data['room']
    friend = data['friend']
    logger = get_logger(room)
    if room in games:
        games[room]['selected_friend'] = friend
        emit('navigate_to_judge_guess', {'room': room}, room=room)
        logger.info(f"Friend selected: {friend} in room {room}")
        for handler in logger.handlers:
            handler.flush()

@app.route('/end_game/<code>')
def end_game(code):
    if code not in games:
        return "<h3>Game not found!</h3>", 404
    game = games[code]
    winner = max(game['points'], key=game['points'].get)
    return render_template('end_game.html', code=code, winner=winner, scores=game['points'])
@socketio.on('judge_guess')
def handle_judge_guess(data):
    room = data['room']
    guess = data['guess']
    logger = get_logger(room)
    if room in games:
        game = games[room]
        game['judge_guess'] = guess
        match = guess == game['selected_friend']
        
        # Update points based on match
        if match:
            game['points'][game['players'][game['judge_index']]] += 1
        else:
            game['points'][game['targeted_player']] += 1

        # Log the round result
        logger.info(f"Judge guessed: {guess} in room {room}. Match: {match}")
        
        # Force-update the current state
        emit('navigate_to_results', {'room': room}, room=room)
        for handler in logger.handlers:
            handler.flush()

@app.route('/results/<code>')
def results(code):
    if code not in games:
        return "<h3>Game not found!</h3>", 404
    game = games[code]
    match = game['judge_guess'] == game['selected_friend']
    return render_template(
        'results.html',
        code=code,
        judge=game['players'][game['judge_index']],
        targeted_player=game['targeted_player'],
        selected_friend=game['selected_friend'],
        judge_guess=game['judge_guess'],
        match=match,
        scores=game['points'],
        players=game['players']  # Pass the players list
    )



@socketio.on('start_new_round')
def handle_start_new_round(data):
    room = data['room']
    logger = get_logger(room)

    if room in games:
        game = games[room]

        # Rotate the judge index cyclically
        game['judge_index'] = (game['judge_index'] + 1) % len(game['players'])

        # Determine targeted player and new question
        if len(game['players']) == 2:
            # For 2-player games, automatically rotate targeted player
            game['targeted_player'] = game['players'][1 - game['judge_index']]
            game['current_question'] = get_random_question()

            logger.info(f"New round (2 players): Judge: {game['players'][game['judge_index']]}, "
                        f"Targeted Player: {game['targeted_player']}, "
                        f"Question: {game['current_question']}")
            print("Emitting navigate_to_gameplay")  # Debug print
            emit('navigate_to_gameplay', {'room': room}, room=room)
        else:
            # For multi-player games, reset targeted player for manual selection
            game['targeted_player'] = ''
            game['current_question'] = get_random_question()

            logger.info(f"New round (multi-player): Judge: {game['players'][game['judge_index']]}, "
                        f"Question: {game['current_question']}. Waiting for target selection.")
            print("Emitting navigate_to_round_start")  # Debug print
            emit('navigate_to_round_start', {'room': room}, room=room)

        for handler in logger.handlers:
            handler.flush()

@socketio.on('target_selected')
def handle_target_selected(data):
    room = data['room']
    targeted_player = data['targeted_player']
    logger = get_logger(room)

    if room in games:
        game = games[room]
        game['targeted_player'] = targeted_player  # Update the targeted player
        game['current_question'] = get_random_question()  # Ensure new question for the round

        logger.info(f"Target player selected: {targeted_player} in room {room}")
        
        # Emit navigation to gameplay
        emit('navigate_to_gameplay', {'room': room}, room=room)
        logger.info(f"Emitting navigate_to_gameplay for room {room}")

        for handler in logger.handlers:
            handler.flush()
    else:
        emit('error', {'message': 'Game room not found.'})




if __name__ == "__main__":
    socketio.run(app, debug=True)
