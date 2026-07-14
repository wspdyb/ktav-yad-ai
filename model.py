# -*- coding: utf-8 -*-
"""רשת CRNN (רשת קונבולוציה + BiLSTM + CTC) לזיהוי שורות כתב יד.
קלט: תמונת גווני אפור בגובה 48 פיקסלים, רוחב משתנה.
פלט: רצף הסתברויות תווים לאורך ציר הרוחב (רוחב/4 צעדי זמן).
"""
import torch
import torch.nn as nn

IMG_H = 48
DOWNSAMPLE_W = 4  # פקטור הקטנת הרוחב ברשת


class CRNN(nn.Module):
    def __init__(self, num_classes, nh=256):
        super().__init__()
        self.cnn = nn.Sequential(
            nn.Conv2d(1, 32, 3, 1, 1), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),                       # 48 -> 24, W -> W/2
            nn.Conv2d(32, 64, 3, 1, 1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),                       # 24 -> 12, W -> W/4
            nn.Conv2d(64, 128, 3, 1, 1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
            nn.Conv2d(128, 128, 3, 1, 1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
            nn.MaxPool2d((2, 1)),                     # 12 -> 6
            nn.Conv2d(128, 256, 3, 1, 1), nn.BatchNorm2d(256), nn.ReLU(inplace=True),
            nn.MaxPool2d((2, 1)),                     # 6 -> 3
            nn.Conv2d(256, 256, (3, 1)), nn.BatchNorm2d(256), nn.ReLU(inplace=True),  # 3 -> 1
        )
        self.rnn = nn.LSTM(256, nh, num_layers=2, bidirectional=True,
                           batch_first=True, dropout=0.1)
        self.fc = nn.Linear(nh * 2, num_classes)

    def forward(self, x):                # x: (B, 1, 48, W)
        f = self.cnn(x)                  # (B, 256, 1, W/4)
        f = f.squeeze(2).permute(0, 2, 1)  # (B, T, 256)
        r, _ = self.rnn(f)
        return self.fc(r)                # (B, T, num_classes)


def save_checkpoint(path, model, charset, step=0, meta=None):
    torch.save({"model": model.state_dict(), "charset": charset,
                "step": step, "meta": meta or {}}, path)


def load_checkpoint(path, num_classes, charset):
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    if ckpt.get("charset") != charset:
        raise ValueError(f"charset mismatch in {path} — המודל אומן על מפת תווים שונה")
    model = CRNN(num_classes)
    model.load_state_dict(ckpt["model"])
    return model, ckpt


if __name__ == "__main__":
    from charset import NUM_CLASSES
    m = CRNN(NUM_CLASSES)
    n_params = sum(p.numel() for p in m.parameters())
    x = torch.randn(2, 1, IMG_H, 320)
    y = m(x)
    print(f"params: {n_params/1e6:.1f}M, in {tuple(x.shape)} -> out {tuple(y.shape)}")
