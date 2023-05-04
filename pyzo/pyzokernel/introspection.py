# -*- coding: utf-8 -*-
# Copyright (C) 2016, the Pyzo development team
#
# Pyzo is distributed under the terms of the 2-Clause BSD License.
# The full license can be found in 'license.txt'.

import sys
import yoton
import inspect  # noqa - used in eval()


try:
    import thread  # Python 2
except ImportError:
    import _thread as thread  # Python 3


class PyzoIntrospector(yoton.RepChannel):
    """This is a RepChannel object that runs a thread to respond to
    requests from the IDE.
    """

    def _getNameSpace(self, name=""):
        """_getNameSpace(name='')

        Get the namespace to apply introspection in.
        If name is given, will find that name. For example sys.stdin.

        """

        # Get namespace
        NS1 = sys._pyzoInterpreter.locals
        if NS2 := sys._pyzoInterpreter.globals:
            NS = NS2.copy()
            NS.update(NS1)

        else:
            NS = NS1
        if not name:
            return NS
        try:
            # Get object
            ob = eval(name, None, NS)

                # Get namespace for this object
            if isinstance(ob, dict):
                NS = {f"[{repr(el)}]": ob[el] for el in ob}
            elif isinstance(ob, (list, tuple)):
                NS = {"[%i]" % count: el for count, el in enumerate(ob)}
            else:
                keys = dir(ob)
                NS = {}
                for key in keys:
                    try:
                        NS[key] = getattr(ob, key)
                    except Exception:
                        NS[key] = "<unknown>"

            # Done
            return NS

        except Exception:
            return {}

    def _getSignature(self, objectName):
        """_getSignature(objectName)

        Get the signature of builtin, function or method.
        Returns a tuple (signature_string, kind), where kind is a string
        of one of the above. When none of the above, both elements in
        the tuple are an empty string.

        """

        # if a class, get init
        # not if an instance! -> try __call__ instead
        # what about self?

        # Get valid object names
        parts = objectName.rsplit(".")
        objectNames = [".".join(parts[-i:]) for i in range(1, len(parts) + 1)]

        # find out what kind of function, or if a function at all!
        NS = self._getNameSpace()
        fun1 = eval(f"inspect.isbuiltin({objectName})", None, NS)
        fun2 = eval(f"inspect.isfunction({objectName})", None, NS)
        fun3 = eval(f"inspect.ismethod({objectName})", None, NS)
        fun4 = False
        fun5 = False
        if not (fun1 or fun2 or fun3):
            # Maybe it's a class with an init?
            if eval(f"hasattr({objectName},'__init__')", None, NS):
                objectName += ".__init__"
                fun4 = eval(f"inspect.ismethod({objectName})", None, NS)
            elif eval(f"hasattr({objectName},'__call__')", None, NS):
                objectName += ".__call__"
                fun5 = eval(f"inspect.ismethod({objectName})", None, NS)

        sigs = ""
            # the first line in the docstring is usually the signature
        tmp = eval(f"{objectNames[-1]}.__doc__", {}, NS)
        sigs = ""
        if tmp:
            sigs = tmp.splitlines()[0].strip()
        # Test if doc has signature
        hasSig = False
        for name in objectNames:  # list.append -> L.apend(objec) -- blabla
            name += "("
            if name in sigs:
                hasSig = True
        # If not a valid signature, do not bother ...
        if (not hasSig) or (sigs.count("(") != sigs.count(")")):
            sigs = ""

        if fun1 or fun2 or fun3 or fun4 or fun5:

            if fun1:
                kind = "builtin"
            elif fun2:
                kind = "function"
            elif fun3:
                kind = "method"
            elif fun4:
                kind = "class"
            else:
                kind = "callable"

            if not sigs:
                # Use intospection

                funname = objectName.split(".")[-1]

                try:
                    tmp = eval(f"inspect.signature({objectName})", None, NS)
                    sigs = funname + str(tmp)
                except Exception:
                    try:
                        tmp = eval(f"inspect.getargspec({objectName})", None, NS)
                    except Exception:  # the above fails on 2.4 (+?) for builtins
                        tmp = None
                        kind = ""

                    if tmp is not None:
                        args, varargs, varkw, defaults = tmp[:4]
                        # prepare defaults
                        if defaults is None:
                            defaults = ()
                        defaults = list(defaults)
                        defaults.reverse()
                        # make list (back to forth)
                        args2 = []
                        for i in range(len(args) - fun4):
                            arg = args.pop()
                            if i < len(defaults):
                                args2.insert(0, f"{arg}={defaults[i]}")
                            else:
                                args2.insert(0, arg)
                        # append varargs and kwargs
                        if varargs:
                            args2.append(f"*{varargs}")
                        if varkw:
                            args2.append(f"**{varkw}")
                        # append the lot to our  string
                        sigs = f'{funname}({", ".join(args2)})'

        elif sigs:
            kind = "function"
        else:
            sigs = ""
            kind = ""

        return sigs, kind

    # todo: variant that also says whether it's a property/function/class/other
    def dir(self, objectName):
        """dir(objectName)

        Get list of attributes for the given name.

        """
        # sys.__stdout__.write('handling '+objectName+'\n')
        # sys.__stdout__.flush()

        # Get namespace
        NS = self._getNameSpace()

        # Init names
        names = set()

        # Obtain all attributes of the class
        try:
            command = f"dir({objectName}.__class__)"
            d = eval(command, {}, NS)
        except Exception:
            pass
        else:
            names.update(d)

        # Obtain instance attributes
        try:
            command = f"{objectName}.__dict__.keys()"
            d = eval(command, {}, NS)
        except Exception:
            pass
        else:
            names.update(d)

        # That should be enough, but in case __dir__ is overloaded,
        # query that as well
        try:
            command = f"dir({objectName})"
            d = eval(command, {}, NS)
        except Exception:
            pass
        else:
            names.update(d)

        # Respond
        return list(names)

    def dir2(self, objectName):
        """dir2(objectName)

        Get variable names in currently active namespace plus extra information.
        Returns a list of tuple of strings: name, type, kind, repr.

        """
        try:
            name = ""
            names = []

            def storeInfo(name, val):
                # Determine type
                typeName = type(val).__name__
                # Determine kind
                kind = typeName
                if typeName != "type":
                    if (
                        hasattr(val, "__array__")
                        and hasattr(val, "dtype")
                        and hasattr(val, "shape")
                    ):
                        kind = "array"
                    elif isinstance(val, list):
                        kind = "list"
                    elif isinstance(val, tuple):
                        kind = "tuple"
                # Determine representation
                if kind == "array":
                    tmp = "x".join([str(s) for s in val.shape])
                    if tmp:
                        values_repr = ""
                        if hasattr(val, "flat"):
                            for el in val.flat:
                                values_repr += f", {repr(el)}"
                                if len(values_repr) > 70:
                                    values_repr = f"{values_repr[:67]}, …"
                                    break
                        repres = f"<array {tmp} {val.dtype.name}: {values_repr}>"
                    elif val.size:
                        tmp = str(float(val))
                        if "int" in val.dtype.name:
                            tmp = str(int(val))
                        repres = f"<array scalar {val.dtype.name} ({tmp})>"
                    else:
                        repres = f"<array empty {val.dtype.name}>"
                elif kind == "list":
                    values_repr = ""
                    for el in val:
                        values_repr += f", {repr(el)}"
                        if len(values_repr) > 70:
                            values_repr = f"{values_repr[:67]}, …"
                            break
                    repres = "<%i-element list: %s>" % (len(val), values_repr)
                elif kind == "tuple":
                    values_repr = ""
                    for el in val:
                        values_repr += f", {repr(el)}"
                        if len(values_repr) > 70:
                            values_repr = f"{values_repr[:67]}, …"
                            break
                    repres = "<%i-element tuple: %s>" % (len(val), values_repr)
                elif kind == "dict":
                    values_repr = ""
                    for k, v in val.items():
                        values_repr += f", {repr(k)}: {repr(v)}"
                        if len(values_repr) > 70:
                            values_repr = f"{values_repr[:67]}, …"
                            break
                    repres = "<%i-item dict: %s>" % (len(val), values_repr)
                else:
                    repres = repr(val)
                    if len(repres) > 80:
                        repres = f"{repres[:77]}…"
                # Store
                tmp = (name, typeName, kind, repres)
                names.append(tmp)

            # Get locals
            NS = self._getNameSpace(objectName)
            for name in NS.keys():  # name can be a key in a dict, i.e. not str
                if hasattr(name, "startswith") and name.startswith("__"):
                    continue
                try:
                    storeInfo(str(name), NS[name])
                except Exception:
                    pass

            return names

        except Exception:
            return []

    def signature(self, objectName):
        """signature(objectName)

        Get signature.

        """
        try:
            text, kind = self._getSignature(objectName)
            return text
        except Exception:
            return None

    def doc(self, objectName):
        """doc(objectName)

        Get documentation for an object.

        """

        # Get namespace
        NS = self._getNameSpace()

        try:

            # collect docstring
            h_text = ""
            # Try using the class (for properties)
            try:
                className = eval(f"{objectName}.__class__.__name__", {}, NS)
                if "." in objectName:
                    tmp = objectName.rsplit(".", 1)
                    tmp[1] += "."
                else:
                    tmp = [objectName, ""]
                if className not in [
                    "type",
                    "module",
                    "builtin_function_or_method",
                    "function",
                ]:
                    h_text = eval(f"{tmp[0]}.__class__.{tmp[1]}__doc__", {}, NS)
            except Exception:
                pass

            # Normal doc
            if not h_text:
                h_text = eval(f"{objectName}.__doc__", {}, NS)

            # collect more data
            h_repr = eval(f"repr({objectName})", {}, NS)
            try:
                h_class = eval(f"{objectName}.__class__.__name__", {}, NS)
            except Exception:
                h_class = "unknown"

            # docstring can be None, but should be empty then
            if not h_text:
                h_text = ""

            # get and correct signature
            h_fun, kind = self._getSignature(objectName)

            if not h_fun:
                h_fun = ""  # signature not available

            # cut repr if too long
            if len(h_repr) > 200:
                h_repr = f"{h_repr[:200]}..."
            # replace newlines so we can separates the different parts
            h_repr = h_repr.replace("\n", "\r")

            # build final text
            text = "\n".join([objectName, h_class, h_fun, h_repr, h_text])

        except Exception:
            type, value, tb = sys.exc_info()
            del tb
            text = "\n".join(
                [objectName, "", "", "", "No help available. ", str(value)]
            )

        # Done
        return text

    def eval(self, command):
        """eval(command)

        Evaluate a command and return result.

        """

        # Get namespace
        NS = self._getNameSpace()

        try:
            # here globals is None, so we can look into sys, time, etc...
            return eval(command, None, NS)
        except Exception:
            return f"Error evaluating: {command}"

    def interrupt(self, command=None):
        """interrupt()

        Interrupt the main thread. This does not work if the main thread
        is running extension code.

        A bit of a hack to do this in the introspector, but it's the
        easeast way and prevents having to launch another thread just
        to wait for an interrupt/terminare command.

        Note that on POSIX we can send an OS INT signal, which is faster
        and maybe more effective in some situations.

        """
        thread.interrupt_main()

    def terminate(self, command=None):
        """terminate()

        Ask the kernel to terminate by closing the stdin.

        """
        sys.stdin._channel.close()
