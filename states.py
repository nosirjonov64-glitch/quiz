from aiogram.fsm.state import State, StatesGroup

class AdminFlow(StatesGroup):
    category_name = State()
    quiz_category = State()
    quiz_question = State()
    quiz_options = State()
    quiz_correct = State()
    quiz_explanation = State()
    admin_id = State()
    remove_admin_id = State()
    interval = State()
    channel_id = State()

class UserFlow(StatesGroup):
    interval = State()
