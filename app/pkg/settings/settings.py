import os

from dynaconf import Dynaconf

# Абсолютный путь, чтобы настройки загружались независимо от рабочей директории процесса
# (магазин запускается из корня репозитория, тесты могут запускаться из другого места).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

settings = Dynaconf(
    envvar_prefix=False,
    environments=True,
    load_dotenv=True,
    root_path=_ROOT,
    settings_files=["config/settings.yml", "settings.yml"],
)
