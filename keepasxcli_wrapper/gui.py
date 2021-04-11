import os
from tkinter import simpledialog, Entry, Label, W, LEFT, E, END, messagebox, Tk
from tkinter.simpledialog import Dialog, askstring


def get_password_with_dialog(database):
    os.environ['TK_SILENCE_DEPRECATION'] = '1'
    tk = Tk()
    tk.withdraw()
    title = 'Opening database ' + database
    prompt = "Password for database:\n" + database

    pw = askstring(title, prompt, show='*')
    tk.destroy()
    return pw

