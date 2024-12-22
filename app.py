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
        # Add a timestamp to the log filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')  # Format: YYYYMMDD_HHMMSS
        log_file = os.path.join(LOG_DIR, f"{timestamp}_game_{game_code}.log")

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
            game_code = ''.join(random.choices("1234567890", k=4))
            while game_code in games:  # Ensure unique code
                game_code = ''.join(random.choices("1234567890", k=4))
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
    
    game = games[code]
    return render_template('lobby.html', code=code, players=game['players'])

@app.route('/setup/<code>')
def setup(code):
    if code not in games:
        return "<h3>Game not found!</h3>", 404

    game = games[code]

    # Initialize the first question if not already set
    if not game['current_question']:
        game['current_question'] = get_random_question()

    logger = get_logger(code)
    logger.info(f"Navigating to setup for room {code}. Current game state: {game}")
    return render_template('setup.html', code=code)

@app.route('/round_start/<code>')
def round_start(code):
    if code not in games:
        return "<h3>Game not found!</h3>", 404

    game = games[code]
    judge = game['players'][game['judge_index']]
    game['random_friends'] = random.sample(game['friends'], min(5, len(game['friends'])))

    # Assign targeted player if not set (first round)
    if not game['targeted_player']:
        if len(game['players']) == 2:  # Two-player game
            game['targeted_player'] = game['players'][1 - game['judge_index']]
        else:  # Multi-player game
            game['targeted_player'] = game['players'][(game['judge_index'] + 1) % len(game['players'])]

    return render_template(
        'roundstart.html', 
        code=code, 
        judge=judge, 
        question=game['current_question'], 
        players=game['players'],
        friends=game['random_friends']
    )


@app.route('/gameplay/<code>')
def gameplay(code):
    if code not in games:
        return "<h3>Game not found!</h3>", 404

    game = games[code]
    return render_template(
        'gameplay.html',
        code=code,
        targeted_player=game['targeted_player'],
        question=game['current_question'],
        friends=game['random_friends'],  # Use the subset
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
        question=game['current_question'], 
        friends=game['random_friends'],  # Use the subset
        scores=game['points']
    )
@socketio.on('join')
def handle_join(data):
    room = data['room']
    if room in games:
        join_room(room)
        logger = get_logger(room)
        logger.info(f"User joined room {room}")

        # Send the current question to all players
        emit('update_question', {'question': games[room]['current_question']}, room=room)
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

# @socketio.on('submit_friends')
# def handle_submit_friends(data):
#     room = data['room']
#     friends = data['friends']
#     logger = get_logger(room)
#     if room in games and len(friends) >= 5:  # Ensure exactly 5 friends are submitted
#         games[room]['friends'] = friends
#         emit('navigate_to_round_start', {'room': room}, room=room)
#         logger.info(f"Friends list submitted in room {room}: {friends}")
#         for handler in logger.handlers:
#             handler.flush()
#     else:
#         emit('error', {'message': 'Invalid friends list.'})

@socketio.on('add_friends')
def handle_add_friends(data):
    room = data['room']
    new_friends = data['friends']
    logger = get_logger(room)

    if room in games:
        game = games[room]
        # Add new friends to the list, avoiding duplicates
        game['friends'].extend(friend for friend in new_friends if friend not in game['friends'])

        logger.info(f"Friends added in room {room}: {new_friends}")
        emit('update_friends_list', {'friends': game['friends']}, room=room)  # Broadcast updated list to all players

        for handler in logger.handlers:
            handler.flush()
    else:
        emit('error', {'message': 'Room not found.'})


@socketio.on('submit_friends')
def handle_submit_friends(data):
    room = data['room']
    logger = get_logger(room)

    if room in games:
        emit('navigate_to_round_start', {'room': room}, room=room)  # Navigate to the next screen
        logger.info(f"Friends list finalized in room {room}: {games[room]['friends']}")
    else:
        emit('error', {'message': 'Room not found.'})

@socketio.on('begin_game')
def handle_begin_game(data):
    room = data['room']
    logger = get_logger(room)

    if room in games:
        game = games[room]
        logger.info(f"Begin Game called for room {room}. Current state: {game}")

        if len(game['players']) >= 2:
            # Ensure the game has required data
            if not game['current_question']:
                game['current_question'] = get_random_question()

            if len(game['players']) == 2:
                game['targeted_player'] = game['players'][1 - game['judge_index']]
            else:
                game['targeted_player'] = game['players'][(game['judge_index'] + 1) % len(game['players'])]

            logger.info(f"Game successfully started for room {room}. Targeted player: {game['targeted_player']}")

            # Ensure all clients are ready before navigating
            socketio.sleep(1)  # Optional: Short delay to allow client connection
            emit('navigate_to_setup', {'room': room}, room=room)
        else:
            logger.warning(f"Insufficient players to start game in room {room}. Players: {game['players']}")
            emit('error', {'message': 'Not enough players to start the game.'})
    else:
        logger.error(f"Begin Game attempted for non-existent room {room}.")
        emit('error', {'message': 'Room not found.'})


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

        # Update points based on guess
        if match:
            game['points'][game['players'][game['judge_index']]] += 1
        else:
            game['points'][game['targeted_player']] += 1

        # Log the result
        logger.info(f"Judge guessed: {guess} in room {room}. Match: {match}")

        # Check for a winner (10 points)
        for player, points in game['points'].items():
            if points >= 2:
                logger.info(f"Game over! {player} has reached 10 points in room {room}")
                emit('navigate_to_end_game', {'room': room, 'winner': player, 'scores': game['points']}, room=room)
                return  # Stop further execution to avoid conflicting emits



        # Proceed to results page if no winner
        emit('navigate_to_results', {'room': room}, room=room)
        logger.info(f"Navigating to results for room {room}")

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

        # Set a new question
        game['current_question'] = get_random_question()

        # Regenerate a new random set of friends for the round
        game['random_friends'] = random.sample(game['friends'], min(5, len(game['friends'])))

        if len(game['players']) == 2:
            game['targeted_player'] = game['players'][1 - game['judge_index']]
            logger.info(f"New round (2 players): Judge: {game['players'][game['judge_index']]}, "
                        f"Targeted Player: {game['targeted_player']}, "
                        f"Question: {game['current_question']}, "
                        f"Random Friends: {game['random_friends']}")

            # Emit the updated question and random friends to all clients
            emit('update_question', {'question': game['current_question']}, room=room)
            emit('navigate_to_gameplay', {'room': room}, room=room)
        else:
            game['targeted_player'] = ''
            logger.info(f"New round (multi-player): Judge: {game['players'][game['judge_index']]}, "
                        f"Question: {game['current_question']}, "
                        f"Random Friends: {game['random_friends']}. Waiting for target selection.")
            emit('update_question', {'question': game['current_question']}, room=room)
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
        game['targeted_player'] = targeted_player  # Update targeted player

        logger.info(f"Target player selected: {targeted_player} in room {room}")

        # Emit the already set question to all clients
        emit('update_question', {'question': game['current_question']}, room=room)
        emit('navigate_to_gameplay', {'room': room}, room=room)
        logger.info(f"Emitting navigate_to_gameplay for room {room}")

        for handler in logger.handlers:
            handler.flush()

@app.route('/reset_game/<code>')
def reset_game(code):
    if code in games:
        logger = get_logger(code)
        logger.info(f"Game with code {code} is being reset.")

        # Retain players but reset the rest of the game state
        games[code].update({
            'points': {player: 0 for player in games[code]['players']},
            'judge_index': 0,
            'friends': [],
            'targeted_player': '',
            'current_question': '',
            'selected_friend': '',
            'judge_guess': ''
        })

        # Notify all players to navigate to the lobby
        socketio.emit('navigate_to_lobby', {'room': code}, room=code)
        logger.info(f"All players in room {code} redirected to the lobby.")

    return redirect(url_for('lobby', code=code))




if __name__ == "__main__":
    #socketio.run(app, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=False)

    
    socketio.run(app, host='127.0.0.1', port=5000, debug=True)

