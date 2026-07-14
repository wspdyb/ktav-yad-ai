# -*- coding: utf-8 -*-
"""הרחבת מודל קיים למפת תווים גדולה יותר (תווים חדשים נוספו בסוף המפה).
משאיר את כל המשקולות הקיימות ומוסיף שורות חדשות לשכבת הפלט בלבד."""
import sys
import torch
from charset import CHARSET, NUM_CLASSES
from model import CRNN


def migrate(path):
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    old_charset = ckpt.get("charset", "")
    if old_charset == CHARSET:
        print(f"{path}: כבר במפה העדכנית")
        return
    if not CHARSET.startswith(old_charset):
        raise SystemExit(f"{path}: המפה הישנה אינה רישא של החדשה — הגירה לא בטוחה")
    state = ckpt["model"]
    old_c = len(old_charset) + 1
    w, b = state["fc.weight"], state["fc.bias"]
    assert w.shape[0] == old_c, f"unexpected fc shape {w.shape} vs {old_c}"
    add = NUM_CLASSES - old_c
    new_w = torch.cat([w, torch.randn(add, w.shape[1]) * 0.01], dim=0)
    new_b = torch.cat([b, torch.full((add,), -2.0)], dim=0)
    state["fc.weight"], state["fc.bias"] = new_w, new_b
    # אימות: המודל נטען עם המבנה החדש
    m = CRNN(NUM_CLASSES)
    m.load_state_dict(state)
    ckpt["charset"] = CHARSET
    torch.save(ckpt, path)
    print(f"{path}: הורחב {old_c} -> {NUM_CLASSES} מחלקות")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        migrate(p)
