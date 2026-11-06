import sys
import warnings
warnings.filterwarnings('ignore',message='pkg_resources is deprecated as an API.*',category=UserWarning)
try:
    import pkg_resources
    import ctranslate2
    import av
    import faster_whisper
except ModuleNotFoundError as e:
    print('MISSING_PYTHON_PACKAGE:',e,flush=True)
    sys.exit(20)
except (ImportError,OSError) as e:
    message=str(e)
    print('AUDIO_IMPORT_ERROR:',message,flush=True)
    if 'DLL load failed' in message or 'WinError 126' in message or 'WinError 127' in message:
        sys.exit(21)
    sys.exit(22)
print('Audio engine import OK',flush=True)
