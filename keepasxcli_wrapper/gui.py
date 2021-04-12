import os


def get_password_with_dialog(database):
    from tkinter import Tk
    from tkinter.simpledialog import askstring
    os.environ['TK_SILENCE_DEPRECATION'] = '1'
    tk = Tk()
    tk.withdraw()
    title = 'Opening database ' + database
    prompt = "Password for database:\n" + database

    pw = askstring(title, prompt, show='*')
    tk.destroy()
    return pw

