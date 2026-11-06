# Verification — 2026-11-06

## Verified in the development environment

- Python 3.12 backend compilation and browser JavaScript syntax.
- Windows PowerShell bootstrap syntax parsed without errors.
- Windows CPython 3.12.10 embeddable distribution downloaded from python.org and included.
- Windows x64 wheel dependencies downloaded for CPython 3.12 and installed into the private runtime; Windows dependency metadata checked for missing/conflicting requirements.
- Nine focused automated tests cover upload → queued transcription → summary, SQLite persistence, subtitle export, audio Range requests, origin/Host/token checks, interrupted task recovery, preservation of transcripts after summary failures, duplicate task/edit protection, long-text chunking, and grounding action metadata in source text. Test engines are mocked for deterministic backend tests; actual model tests are separate below.
- Real CPU speech recognition with faster-whisper 1.2.1, small model, int8: an English synthetic recording and an 18-second Mandarin synthetic recording were decoded and transcribed.
- Real local Ollama + Qwen2.5:3b summarization and question answering tested on the Mandarin transcript. The final structured summary preserved “周五之前” for the video task deadline and marked an absent owner as unspecified. A question about how many videos and when returned “周五之前完成三条视频”.
- The initial summary test omitted an explicit deadline; the output was changed to a structured schema, with source-quote checks for actions and source-string checks for owners/deadlines, then retested. This improves grounding but does not guarantee the absence of all AI mistakes.
- Browser UI checks: import form, real background pipeline, progress display, persisted notes, summary and transcript tabs, and error messages. See final app checks below.

## Limits

- Development and model tests ran on Linux. Windows executables and the first-run installer flow cannot be executed on the user's actual Windows machine from this environment. Static checks and bundled wheels do not substitute for that first run.
- No benchmark claim for a particular CPU or long recording; no “real-time” or fixed completion-time promise.
- No broad accuracy evaluation for accents, noisy recordings, speaker identity, or all video codecs.
- Large-language-model summaries can still omit or misunderstand information; the app retains the original transcript and displays a verification notice.

## Additional runtime checks

- Actual Mandarin transcription text: “今天讨论下周的内容计划 / 目标用户是刚开始使用人工智能工具的职场新人 / 请在周五之前完成三条短视频 / 发布后复盘收藏和评论”.
- The sample is short and synthetic. These checks prove that the engines ran and communicated locally; they do not establish broad transcription or summarization accuracy.
- One model-generated overview interpreted an ambiguous phrase about review metrics too broadly. Source evidence and the transcript remain visible so this can be checked. No universal summary-accuracy claim is made.

## Final browser checks

A complete Mandarin MP3 was imported through the UI, then automatically transcribed and summarized with the real local engines. The UI showed the completed state, four timestamped transcript segments, the source-backed Friday task deadline and an absent-owner label. A question submitted through the UI returned the video count and deadline. SRT export generated a downloadable subtitle file. The app displayed and recovered from an earlier engine availability failure without losing the imported recording.


## Windows compatibility correction

A real Windows screenshot exposed that CTranslate2 4.6.0 imports pkg_resources only in its Windows DLL-loading branch. The original bundled setuptools 84.2.1 had removed that module. The corrected bundle pins and includes setuptools 80.9.0, adds a verified offline compatibility wheel, and checks Python module failures separately from DLL runtime failures. The actual Windows resource lookup block was executed with the pinned package and native DLL loading mocked, successfully locating three DLL paths. Repeat repair preserved a test data file, and both requirement files retained the pin. PowerShell scripts passed syntax parsing. This does not substitute for executing native Windows DLLs on Windows.
