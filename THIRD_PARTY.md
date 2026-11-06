# Third-party components

This source repository includes an official setuptools compatibility wheel with its original license metadata. CPython and the audio dependencies are downloaded separately by the Windows launcher. Original license metadata remains with installed packages under the private runtime. This project is not affiliated with VOMO, OpenAI, Microsoft, or Ollama.

Main components:
- Setuptools 80.9.0 — MIT. https://github.com/pypa/setuptools
- CPython 3.12.10 — Python Software Foundation License. https://www.python.org/downloads/release/python-31210/
- faster-whisper 1.2.1 — MIT. https://github.com/SYSTRAN/faster-whisper
- CTranslate2 4.6.0 — MIT. https://github.com/OpenNMT/CTranslate2
- PyAV 16.0.1 — BSD, with bundled FFmpeg libraries under their applicable licenses. https://pyav.org/
- ONNX Runtime 1.23.2 — MIT. https://github.com/microsoft/onnxruntime
- Hugging Face Hub, Tokenizers — Apache-2.0. https://github.com/huggingface
- NumPy — BSD. https://numpy.org/

Ollama, Microsoft VC++ runtime, Whisper model weights and Qwen model weights are downloaded separately from their official providers on first use and are subject to their own terms. They are not included in this ZIP.

- Ollama official Windows documentation: https://github.com/ollama/ollama/blob/main/docs/windows.mdx
- Ollama API documentation: https://docs.ollama.com/api
- Whisper: https://github.com/openai/whisper
- Qwen2.5: https://ollama.com/library/qwen2.5:3b

The bundled sample audio is synthetic speech reading original test text. It is provided only as an app test fixture and contains no real meeting or interview recording.
