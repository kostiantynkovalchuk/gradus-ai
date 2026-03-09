import os

_DIR = os.path.dirname(os.path.abspath(__file__))


def get_solomon_html() -> str:
    return open(os.path.join(_DIR, 'solomon_template.html')).read()
