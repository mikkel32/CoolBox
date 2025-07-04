clipboard = ""

def copy(text):
    global clipboard
    clipboard = text


def paste():
    return clipboard
