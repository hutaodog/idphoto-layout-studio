def __getattr__(name):  # PATCH-2: lazy import, beauty_tools pulls in grind_skin
    if name == "BeautyTools":
        from .beauty_tools import BeautyTools
        return BeautyTools
    raise AttributeError(name)
