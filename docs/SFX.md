# Optional sample SFX

KoalaBattle does not bundle third-party sound effects. Downloads, extracted packs, curated WAVs,
and the local manifest stay below the Git-ignored `data/` tree. The repository contains only this
instruction and the example mapping.

## Recommended sources

- [Kenney Digital Audio](https://www.kenney.nl/assets/digital-audio) and
  [Kenney RPG Audio](https://www.kenney.nl/assets/rpg-audio): small CC0 packs for UI, switch,
  heal, miss, basic impacts, and short result stings. Kenney's [support page](https://kenney.nl/support)
  documents the CC0/public-domain terms.
- [Sonniss GameAudioGDC](https://sonniss.com/gameaudiogdc/): large, high-quality libraries for
  whooshes, heavy impacts, energy, elemental, crowd, victory, and failure sounds. Review the
  [bundle licence](https://sonniss.com/gdc-bundle-license/); do not redistribute raw files or use
  them as AI/ML training data.
- [Freesound](https://freesound.org/): use only individually verified CC0 files unless the
  production explicitly carries the required attribution. The [licence FAQ](https://freesound.org/help/faq/)
  explains why the licence must be checked per file.

Do not automate downloads from sources that require accepting a licence or downloading a large
archive. Do not commit raw samples, extracted packs, or the generated manifest.

## Install a curated pack

1. Download a pack from its official page and read its licence.
2. Extract it locally, for example to `data/vendor/audio/kenney-rpg/`.
3. Copy `docs/sfx-mapping.example.json` to
   `data/vendor/audio/kenney-rpg-mapping.json` and replace the example paths with paths that exist
   inside the extracted pack. The mapping keys are KoalaBattle event ids; lists create variants.
4. Install only the mapped files:

   ```bash
   python3 scripts/setup_sfx.py install \
     --source data/vendor/audio/kenney-rpg \
     --mapping data/vendor/audio/kenney-rpg-mapping.json \
     --pack kenney-rpg \
     --source-url https://www.kenney.nl/assets/rpg-audio \
     --license-url https://kenney.nl/support \
     --license CC0
   ```

5. Check the ignored local installation:

   ```bash
   python3 scripts/setup_sfx.py status
   python3 scripts/setup_sfx.py verify
   ```

The installer writes normalized semantic names such as `data/assets/audio/impact-01.wav` and
records the source file, pack, licence URLs, and SHA256 in `data/vendor/sfx-manifest.json`.
`remove` deletes only files listed in that manifest:

```bash
python3 scripts/setup_sfx.py remove --pack kenney-rpg
```

Missing or unsupported samples never break playback. The browser SFX engine falls back to the
existing synthesized cue until a matching local sample is installed.
