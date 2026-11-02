"""NLP-модули системы.

Natasha зависит от pymorphy2, который не работает на Python 3.11+. У pymorphy3
тот же интерфейс, поэтому он подставляется под этим именем до импорта Natasha.
"""
import sys

import pymorphy3

sys.modules["pymorphy2"] = pymorphy3
