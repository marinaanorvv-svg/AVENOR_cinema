"""Заглушка tkinter для смоук-тестов без дисплея и без установленного Tk.

Проверяет, что код экранов выполняется (нет опечаток, верные вызовы сервисов,
правильная логика обработчиков). Корректность параметров настоящих виджетов она
НЕ проверяет — это возможно только запуском программы с реальным Tk.
"""
import os
import sys
import types

CREATED = []   # все созданные «виджеты»: тесты находят в нём открытые диалоги


class TclError(Exception):
    pass


class Widget:
    def __init__(self, master=None, *args, **kwargs):
        self.master, self._children, self._opts = master, [], dict(kwargs)
        self._destroyed = False
        if hasattr(master, "_children"):
            master._children.append(self)
        CREATED.append(self)

    def winfo_screenwidth(self):
        return 1600

    def winfo_screenheight(self):
        return 1000

    def winfo_children(self):
        return list(self._children)

    def destroy(self):
        for child in list(self._children):
            child.destroy()
        if hasattr(self.master, "_children") and self in self.master._children:
            self.master._children.remove(self)
        self._destroyed = True

    def configure(self, **kwargs):
        self._opts.update(kwargs)

    config = configure

    def cget(self, key):
        return self._opts.get(key)

    def winfo_toplevel(self):
        return self

    # размеры и координаты окна: в настоящем Tk это числа
    winfo_width = winfo_height = winfo_reqwidth = winfo_reqheight = lambda self: 800
    winfo_rootx = winfo_rooty = lambda self: 0

    def __getattr__(self, name):   # pack, grid, bind, after, focus_set, title ... — ничего не делают
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *args, **kwargs: None


class Treeview(Widget):
    def __init__(self, master=None, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.rows, self._selection = {}, ()

    def insert(self, parent, index, iid=None, values=(), tags=()):
        self.rows[iid] = {"values": tuple(values), "tags": tuple(tags)}
        return iid

    def get_children(self, item=""):
        return tuple(self.rows)

    def delete(self, *items):
        for item in items:
            self.rows.pop(item, None)

    def selection(self):
        return self._selection

    def selection_set(self, *items):
        self._selection = tuple(items)


class Combobox(Widget):
    def __init__(self, master=None, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self._text = ""

    def get(self):
        return self._text

    def set(self, value):
        self._text = value


class Text(Widget):
    def __init__(self, master=None, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self._content = ""

    def insert(self, index, text):
        self._content += text

    def delete(self, first, last=None):
        self._content = ""

    def get(self, first, last=None):
        return self._content + "\n"   # как в настоящем Tk: в конце добавляется перевод строки


class Style:
    def __init__(self, master=None):
        pass

    def configure(self, style_name, **options):
        pass

    def map(self, style_name, **options):
        pass

    def theme_use(self, name=None):
        pass


class Var:
    def __init__(self, master=None, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value
        for callback in list(getattr(self, "_traces", [])):
            callback()

    def trace_add(self, mode, callback):
        self.__dict__.setdefault("_traces", []).append(lambda: callback())
        return "trace"


class BooleanVar(Var):
    def __init__(self, master=None, value=False):
        super().__init__(master, value)


class PhotoImage:
    def __init__(self, file=None, **kwargs):
        if not file or not os.path.isfile(file):
            raise TclError(f"couldn't open {file}")

    def width(self):
        return 100

    def height(self):
        return 270

    def subsample(self, factor):
        return self


class FakeFont:
    def __init__(self, *args, **kwargs):
        pass

    def configure(self, **kwargs):
        pass

    def measure(self, text):
        return len(text) * 8

    def actual(self, option):
        return {"family": "Sans", "size": 10}.get(option)


class Messagebox:
    """Записывает вызовы окон сообщений; askyesno отвечает значением .answer."""

    def __init__(self):
        self.calls, self.answer = [], True

    def reset(self):
        self.calls.clear()
        self.answer = True

    def showinfo(self, title, message, **kwargs):
        self.calls.append(("info", title, message))

    def showwarning(self, title, message, **kwargs):
        self.calls.append(("warning", title, message))

    def showerror(self, title, message, **kwargs):
        self.calls.append(("error", title, message))

    def askyesno(self, title, message, **kwargs):
        self.calls.append(("confirm", title, message))
        return self.answer


class Filedialog:
    """Диалоги выбора файла возвращают заранее заданный путь .result ('' — отмена)."""

    def __init__(self):
        self.result = ""

    def askopenfilename(self, **kwargs):
        return self.result

    def asksaveasfilename(self, **kwargs):
        return self.result


MESSAGEBOX, FILEDIALOG = Messagebox(), Filedialog()
_NAMES = ("tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.font", "tkinter.filedialog")


def reset():
    CREATED.clear()
    MESSAGEBOX.reset()
    FILEDIALOG.result = ""


def install():
    """Подставляет заглушки в sys.modules. Возвращает прежние модули для restore()."""
    saved = {name: sys.modules.get(name) for name in _NAMES}
    tk, ttk = types.ModuleType("tkinter"), types.ModuleType("tkinter.ttk")
    font, mb = types.ModuleType("tkinter.font"), types.ModuleType("tkinter.messagebox")
    fd = types.ModuleType("tkinter.filedialog")

    tk.TclError, tk.StringVar, tk.BooleanVar, tk.PhotoImage = TclError, Var, BooleanVar, PhotoImage
    tk.Toplevel = tk.Frame = tk.Tk = tk.Label = tk.Canvas = tk.Entry = Widget
    tk.Text = Text
    for name in ("Frame", "Label", "Button", "Entry", "Scrollbar", "Separator", "Checkbutton", "LabelFrame"):
        setattr(ttk, name, Widget)
    ttk.Treeview, ttk.Style, ttk.Combobox = Treeview, Style, Combobox
    font.Font, font.nametofont, font.families = FakeFont, lambda name: FakeFont(), lambda root=None: ["Segoe UI"]
    mb.showinfo, mb.showwarning, mb.showerror, mb.askyesno = (
        MESSAGEBOX.showinfo, MESSAGEBOX.showwarning, MESSAGEBOX.showerror, MESSAGEBOX.askyesno)
    fd.askopenfilename, fd.asksaveasfilename = FILEDIALOG.askopenfilename, FILEDIALOG.asksaveasfilename
    tk.ttk, tk.font, tk.messagebox, tk.filedialog = ttk, font, mb, fd
    for name, module in zip(_NAMES, (tk, ttk, mb, font, fd)):
        sys.modules[name] = module
    reset()
    return saved


def restore(saved):
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module
    for name in [n for n in sys.modules if n == "gui" or n.startswith("gui.")]:
        if name not in ("gui", "gui.formatting", "gui.navigation", "gui.login_guard"):
            sys.modules.pop(name, None)   # модули, импортированные с заглушкой, не должны «протекать»
