import sys


def main():
    from PySide6.QtWidgets import QApplication
    from bsae.gui.window import Window
    app=QApplication.instance() or QApplication(sys.argv)
    window=Window(); window.show()
    return app.exec()


if __name__=='__main__':
    raise SystemExit(main())
