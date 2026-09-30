"""Whole-block admission for historical afterimage cues and selected pages."""

import uuid


class AfterimagePrompt(str):
    def __new__(cls, ambient, selection, store):
        protected = selection.get("protected", False)
        block = ("\n\n" + selection["text"] if protected else
                 "Optional historical context (reference only, not a new request). "
                 "Revisiting it is optional.\n"
                 + selection["text"] + "\nEnd optional memory.\n\n")
        obj = super().__new__(cls, str(ambient) + block if protected else block + str(ambient))
        obj.ambient = str(ambient)
        obj.selection = selection
        obj.store = store
        obj.block = block
        return obj

    def compose(self, ambient):
        return (str(ambient) + self.block if self.selection.get("protected")
                else self.block + str(ambient))

    def with_ambient(self, ambient):
        return AfterimagePrompt(ambient, self.selection, self.store)


def selected_page_prompt(ambient, page, store):
    selection = dict(page, opportunity_id="open_" + uuid.uuid4().hex, receiver=store.actor)
    return AfterimagePrompt(ambient, selection, store)


def record_attempt(prompt, messages, backend, model, outcome="final_request_prepared", reason=None):
    if isinstance(prompt, AfterimagePrompt):
        return prompt.store.exposure(prompt.selection, messages, backend, model, outcome, reason)
    return None
