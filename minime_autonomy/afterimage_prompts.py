"""Whole-block admission for historical afterimage cues and selected pages."""

import uuid


class AfterimagePrompt(str):
    def __new__(cls, ambient, selection, store):
        block = "\n\n" + selection["text"]
        obj = super().__new__(cls, str(ambient) + block)
        obj.ambient = str(ambient)
        obj.selection = selection
        obj.store = store
        obj.block = block
        return obj

    def with_ambient(self, ambient):
        return AfterimagePrompt(ambient, self.selection, self.store)


def selected_page_prompt(ambient, page, store):
    selection = dict(page, opportunity_id="open_" + uuid.uuid4().hex, receiver=store.actor)
    return AfterimagePrompt(ambient, selection, store)


def record_attempt(prompt, messages, backend, model, outcome="final_request_prepared", reason=None):
    if isinstance(prompt, AfterimagePrompt):
        return prompt.store.exposure(prompt.selection, messages, backend, model, outcome, reason)
    return None
