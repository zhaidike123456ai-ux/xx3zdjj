# Third-party notices

The root MIT license applies to this project's code and documentation. Third-party materials retain their own licenses and notices.

## Bundled Jianying templates

- Upstream: [GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft).
- Copyright 2024 Gary Guan.
- License: [Apache License 2.0](assets/jianying/LICENSE).
- Files: `assets/jianying/draft_content_template.json` and `assets/jianying/draft_meta_info.json`.
- Provenance, source URLs, SHA-256 digests and adaptation notes: [source-manifest.json](assets/jianying/source-manifest.json).
- The bundled template bytes are retained unchanged. The adapter creates new project IDs and project-local resource references when generating a candidate; it does not imply endorsement or universal compatibility with Jianying.

## Visual assets

`assets/default-background.jpg` is the plain black grid authorized for distribution with this Skill. The optional third-party teaching screenshot used during local layout work is excluded from this public distribution. Users can supply their own reference images.

## External software and models

Runtime packages and model weights are downloaded separately only within the user's authorization. They are not relicensed by this repository. Consult the original projects' licenses, including:

- [Python](https://docs.python.org/3/license.html)
- [FFmpeg](https://ffmpeg.org/legal.html); licensing depends on the selected build
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [Systran/faster-whisper-medium](https://huggingface.co/Systran/faster-whisper-medium)
- [Node.js](https://github.com/nodejs/node/blob/main/LICENSE)
- [Remotion](https://www.remotion.dev/license)
- [HyperFrames](https://github.com/heygen-com/hyperframes)
- [uv](https://github.com/astral-sh/uv)
- [micromamba](https://github.com/mamba-org/mamba)

The Skill does not purchase subscriptions or bundle system fonts. Users remain responsible for the permitted use of their chosen dependencies and media.
