import re
from dataclasses import replace

from livekit.agents import tokenize
from livekit.plugins import sarvam

ABBREVIATIONS = {"rs", "mr", "mrs", "ms", "dr", "st", "no", "vs", "approx"}


class PhraseTokenizer(tokenize.SentenceTokenizer):
    def __init__(self, protected=lambda: ()):
        self.protected = protected

    def tokenize(self, text, *, language=None):
        stream = self.stream(language=language)
        return stream.split(text, final=True)[0]

    def stream(self, *, language=None):
        return PhraseStream(self.protected)


class PhraseStream(tokenize.SentenceStream):
    def __init__(self, protected):
        super().__init__()
        self.protected = protected
        self.buffer = ""

    def split(self, text, final=False):
        folded = text.lower()
        spans = []
        for name in self.protected():
            if not name:
                continue
            name = name.lower()
            for match in re.finditer(re.escape(name), folded):
                spans.append((match.start(), match.end()))
            for index in range(max(0, len(text) - len(name)), len(text)):
                if name.startswith(folded[index:]) and len(folded[index:]) < len(name):
                    spans.append((index, len(text) + 1))
        parts = []
        start = 0
        for match in re.finditer(r"[.!?;।॥]", text):
            index = match.start()
            if any(left <= index < right for left, right in spans):
                continue
            if text[index] == ".":
                token = re.search(r"([\w.]+)$", text[start:index])
                word = token.group(1).lower() if token else ""
                if (
                    word in ABBREVIATIONS
                    or len(word) == 1
                    or re.fullmatch(r"(?:[a-z]\.)+[a-z]?", word)
                ):
                    continue
                following = text[index + 1 : index + 2]
                if (index and text[index - 1].isdigit()) and (
                    not following or following.isdigit()
                ):
                    continue
                if following and not following.isspace():
                    continue
            elif index + 1 < len(text) and not text[index + 1].isspace():
                continue
            phrase = text[start : index + 1]
            if any(char.isalnum() for char in phrase):
                parts.append(phrase)
            start = index + 1
        tail = text[start:]
        if final:
            if any(char.isalnum() for char in tail):
                parts.append(tail)
            tail = ""
        return parts, tail

    def push_text(self, text):
        self._check_not_closed()
        self.buffer += text
        parts, self.buffer = self.split(self.buffer)
        for part in parts:
            self._event_ch.send_nowait(tokenize.TokenData(token=part))

    def flush(self):
        self._check_not_closed()
        parts, self.buffer = self.split(self.buffer, final=True)
        for part in parts:
            self._event_ch.send_nowait(tokenize.TokenData(token=part))

    def end_input(self):
        self.flush()
        self._do_close()

    async def aclose(self):
        self.buffer = ""
        self._do_close()


class StreamingSarvamTTS(sarvam.TTS):
    def __init__(self, *, protected=lambda: (), **kwargs):
        super().__init__(**kwargs)
        self._opts = replace(self._opts, word_tokenizer=PhraseTokenizer(protected))
