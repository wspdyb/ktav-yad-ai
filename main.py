# -*- coding: utf-8 -*-
"""נקודת הכניסה של התוכנה — זהו הקובץ שנארז ל-EXE.

שני מצבים:
  KtavYadAI.exe               ← פותח את התוכנה (שרת + חלון)
  KtavYadAI.exe --train <שם>  ← מריץ שרשרת אימון (אישי+כללי) ברקע —
                                 כך התוכנה מפעילה אימון עצמאי גם כשהיא ארוזה
"""
import sys
import multiprocessing


def run():
    import paths  # noqa: F401 — מאתחל תיקיות נתונים + זריעה ראשונה
    if "--train" in sys.argv:
        i = sys.argv.index("--train")
        writer = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        if writer:
            import train
            if "--personal-only" in sys.argv or "--general-only" in sys.argv:
                target = ("__general__" if "--general-only" in sys.argv else writer)
                train._write_pid()
                try:
                    train.train(target, 2000, 24, 1e-4, resume=True)
                except SystemExit:
                    pass
                finally:
                    train._clear_pid()
            else:
                train.chain(writer)
        return
    import app
    app.main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    run()
