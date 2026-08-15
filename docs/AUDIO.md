# Production audio

Audio is a derived production layer. Battle simulation and immutable battle events never wait
on a browser audio device and never import speech code. A match can own multiple productions,
each with its own profile, timeline revision, voice assignment, overrides, and director state.

`frontend/src/lib/production/audio-engine.ts` is the only playback owner. It provides master,
voice, SFX, and music gains; pauses and seeks stop stale media; destroy releases timers, media
elements, and the Web Audio context. Voice playback ducks music by the active profile's dB
setting. Browser audio begins only after **Enable audio**.

The built-in generic SFX are short Web Audio oscillator cues. No Pokémon cries, commercial
music, or third-party recordings are bundled. Operator-installed music and sound packs belong
under ignored `data/music/` and `data/sound-packs/`; verify their licenses before use.

Generated WAV files live below ignored `data/audio/<hash-prefix>/<hash>.wav`. SQLite stores
hashes, duration, byte count, provider/model/voice identifiers, and a relative path—not audio
blobs. Files are written to a same-directory temporary file, flushed, and atomically renamed.
Empty, oversized, corrupt, partial, or unsupported WAVs are not served. Missing media leaves
captions and visual replay usable.

Back up `data/koalabattle.db` and `data/audio/` together when historical voiced playback must
be retained. Cache cleanup is an operator action; do not remove referenced files during a live
production.
