"""
    DrawingContext module contains classes related to drawing context.

    DrawingContexts are able to be handled directly by the UI system or
    produce javascript or svg to do the drawing.
"""

# standard libraries
import base64
import collections
from contextlib import contextmanager
import copy
import io
import logging
import math
import time
import threading
import uuid
import xml.sax.saxutils

# third party libraries
import numpy
import scipy.misc

# local libraries
from nion.utils import Unicode

# pylint: disable=star-args


class DrawingContext(object):
    """
        Path commands (begin_path, close_path, move_to, line_to, etc.) should not be intermixed
        with transform commands (translate, scale, rotate).
    """

    # TODO: stroke_fill
    # TODO: circle

    __image_id = 0
    __image_id_lock = threading.RLock()

    def __init__(self, storage=None):
        self.commands = []
        self.save_count = 0
        self.__storage = storage

    def copy_from(self, drawing_context):
        assert self.save_count == 0
        assert drawing_context.save_count == 0
        self.commands = drawing_context.commands

    def add(self, drawing_context):
        self.commands.extend(drawing_context.commands)

    def clear(self):
        self.commands = []
        self.save_count = 0

    def to_js(self):
        js = ""
        for command in self.commands:
            command_id = command[0]
            command_args = command[1:]
            if command_id == "save":
                js += "ctx.save();"
            elif command_id == "restore":
                js += "ctx.restore();"
            elif command_id == "beginPath":
                js += "ctx.beginPath();"
            elif command_id == "closePath":
                js += "ctx.closePath();"
            elif command_id == "clip":
                js += "ctx.beginPath();"
                js += "ctx.rect({0}, {1}, {2}, {3});".format(*command_args)
                js += "ctx.clip();"
            elif command_id == "translate":
                js += "ctx.translate({0}, {1});".format(*command_args)
            elif command_id == "scale":
                js += "ctx.scale({0}, {1});".format(*command_args)
            elif command_id == "rotate":
                js += "ctx.rotate({0});".format(*command_args)
            elif command_id == "moveTo":
                js += "ctx.moveTo({0}, {1});".format(*command_args)
            elif command_id == "lineTo":
                js += "ctx.lineTo({0}, {1});".format(*command_args)
            elif command_id == "rect":
                js += "ctx.rect({0}, {1}, {2}, {3});".format(*command_args)
            elif command_id == "arc":
                x, y, r, sa, ea, ac = command_args
                js += "ctx.arc({0}, {1}, {2}, {3}, {4}, {5});".format(x, y, r, sa, ea, "true" if ac else "false")
            elif command_id == "arcTo":
                x1, y1, x2, y2, r = command_args
                js += "ctx.arcTo({0}, {1}, {2}, {3}, {4});".format(x1, y1, x2, y2, r)
            elif command_id == "image":
                w, h, image, image_id, a, b, c, d = command_args
                js += "ctx.rect({0}, {1}, {2}, {3});".format(a, b, c, d)
            elif command_id == "stroke":
                js += "ctx.stroke();"
            elif command_id == "sleep":
                pass  # used for performance testing
            elif command_id == "fill":
                js += "ctx.fill();"
            elif command_id == "fillText":
                text, x, y, max_width = command_args
                js += "ctx.fillText('{0}', {1}, {2}{3});".format(xml.sax.saxutils.escape(text), x, y, ", {0}".format(max_width) if max_width else "")
            elif command_id == "fillStyleGradient":
                command_var = command_args[0]
                js += "ctx.fillStyle = {0};".format("grad" + str(command_var))
            elif command_id == "fillStyle":
                js += "ctx.fillStyle = '{0}';".format(*command_args)
            elif command_id == "font":
                js += "ctx.font = '{0}';".format(*command_args)
            elif command_id == "textAlign":
                js += "ctx.textAlign = '{0}';".format(*command_args)
            elif command_id == "textBaseline":
                js += "ctx.textBaseline = '{0}';".format(*command_args)
            elif command_id == "strokeStyle":
                js += "ctx.strokeStyle = '{0}';".format(*command_args)
            elif command_id == "lineWidth":
                js += "ctx.lineWidth = {0};".format(*command_args)
            elif command_id == "lineDash":
                js += "ctx.lineDash = {0};".format(*command_args)
            elif command_id == "lineCap":
                js += "ctx.lineCap = '{0}';".format(*command_args)
            elif command_id == "lineJoin":
                js += "ctx.lineJoin = '{0}';".format(*command_args)
            elif command_id == "gradient":
                command_var, width, height, x1, y1, x2, y2 = command_args  # pylint: disable=invalid-name
                js_var = "grad" + str(command_var)
                js += "var {0} = ctx.createLinearGradient({1}, {2}, {3}, {4});".format(js_var, x1, y1, x2 - x1, y2 - y1)
            elif command_id == "colorStop":
                command_var, x, color = command_args
                js_var = "grad" + str(command_var)
                js += "{0}.addColorStop({1}, '{2}');".format(js_var, x, color)
        return js

    def to_svg(self, size, viewbox):
        svg = ""
        defs = ""
        path = ""
        next_clip_id = 1
        transform = list()
        closers = list()
        fill_style = None
        stroke_style = None
        line_cap = "square"
        line_join = "bevel"
        line_width = 1.0
        line_dash = None
        text_anchor = "start"
        text_baseline = "alphabetic"
        font_style = None
        font_weight = None
        font_size = None
        font_family = None
        contexts = collections.deque()
        gradient_start = None
        gradient_stops = list()
        for command in self.commands:
            command_id = command[0]
            #logging.debug(command_id)
            command_args = command[1:]
            if command_id == "save":
                context = dict()
                context["path"] = path
                context["transform"] = copy.deepcopy(transform)
                context["fill_style"] = fill_style
                context["stroke_style"] = stroke_style
                context["line_cap"] = line_cap
                context["line_join"] = line_join
                context["line_width"] = line_width
                context["line_dash"] = line_dash
                context["font_style"] = font_style
                context["font_weight"] = font_weight
                context["font_size"] = font_size
                context["font_family"] = font_family
                context["text_anchor"] = text_anchor
                context["text_baseline"] = text_baseline
                context["closers"] = copy.deepcopy(closers)
                closers = list()
                contexts.append(context)
            elif command_id == "restore":
                svg += "".join(closers)
                context = contexts.pop()
                path = context["path"]
                transform = context["transform"]
                fill_style = context["fill_style"]
                font_style = context["font_style"]
                font_weight = context["font_weight"]
                font_size = context["font_size"]
                font_family = context["font_family"]
                text_anchor = context["text_anchor"]
                text_baseline = context["text_baseline"]
                stroke_style = context["stroke_style"]
                line_cap = context["line_cap"]
                line_join = context["line_join"]
                line_width = context["line_width"]
                line_dash = context["line_dash"]
                closers = context["closers"]
            elif command_id == "beginPath":
                path = ""
            elif command_id == "closePath":
                path += " Z"
            elif command_id == "moveTo":
                path += " M {0} {1}".format(*command_args)
            elif command_id == "lineTo":
                path += " L {0} {1}".format(*command_args)
            elif command_id == "rect":
                x, y, w, h = command_args
                path += " M {0} {1}".format(x, y)
                path += " L {0} {1}".format(x + w, y)
                path += " L {0} {1}".format(x + w, y + h)
                path += " L {0} {1}".format(x, y + h)
                path += " Z"
            elif command_id == "arc":
                x, y, r, sa, ea, ac = command_args
                # js += "ctx.arc({0}, {1}, {2}, {3}, {4}, {5});".format(x, y, r, sa, ea, "true" if ac else "false")
            elif command_id == "arcTo":
                x1, y1, x2, y2, r = command_args
                # js += "ctx.arcTo({0}, {1}, {2}, {3}, {4});".format(x1, y1, x2, y2, r)
            elif command_id == "clip":
                x, y, w, h = command_args
                clip_id = "clip" + str(next_clip_id)
                next_clip_id += 1
                transform_str = " transform='{0}'".format(" ".join(transform)) if len(transform) > 0 else ""
                defs_format_str = "<clipPath id='{0}'><rect x='{1}' y='{2}' width='{3}' height='{4}'{5} /></clipPath>"
                defs += defs_format_str.format(clip_id, x, y, w, h, transform_str)
                svg += "<g style='clip-path: url(#{0});'>".format(clip_id)
                closers.append("</g>")
            elif command_id == "translate":
                transform.append("translate({0},{1})".format(*command_args))
            elif command_id == "scale":
                transform.append("scale({0},{1})".format(*command_args))
            elif command_id == "rotate":
                transform.append("rotate({0})".format(*command_args))
            elif command_id == "image":
                w, h, image, image_id, a, b, c, d = command_args
                png_file = io.BytesIO()
                scipy.misc.imsave(png_file, image, "png")
                png_encoded = base64.b64encode(png_file.getvalue()).decode('utf=8')
                transform_str = " transform='{0}'".format(" ".join(transform)) if len(transform) > 0 else ""
                svg_format_str = "<image x='{0}' y='{1}' width='{2}' height='{3}' xlink:href='data:image/png;base64,{4}'{5} />"
                svg += svg_format_str.format(a, b, c, d, png_encoded, transform_str)
            elif command_id == "stroke":
                if stroke_style is not None:
                    transform_str = " transform='{0}'".format(" ".join(transform)) if len(transform) > 0 else ""
                    dash_str = " stroke-dasharray='{0}, {1}'".format(line_dash, line_dash) if line_dash else ""
                    svg_format_str = "<path d='{0}' fill='transparent' stroke='{1}' stroke-width='{2}' stroke-linejoin='{3}' stroke-linecap='{4}'{5}{6} />"
                    svg += svg_format_str.format(path, stroke_style, line_width, line_join, line_cap, dash_str,
                                                 transform_str)
            elif command_id == "sleep":
                pass  # used for performance testing
            elif command_id == "fill":
                if fill_style is not None:
                    transform_str = " transform='{0}'".format(" ".join(transform)) if len(transform) > 0 else ""
                    svg += "<path d='{0}' fill='{1}' stroke='transparent'{2} />".format(path, fill_style, transform_str)
            elif command_id == "fillText":
                text, x, y, max_width = command_args
                transform_str = " transform='{0}'".format(" ".join(transform)) if len(transform) > 0 else ""
                font_str = ""
                if font_style:
                    font_str += " font-style='{0}'".format(font_style)
                if font_weight:
                    font_str += " font-weight='{0}'".format(font_weight)
                if font_size:
                    font_str += " font-size='{0}pt'".format(font_size)
                if font_family:
                    font_str += " font-family='{0}'".format(font_family)
                svg_format_str = "<text x='{0}' y='{1}' text-anchor='{3}' alignment-baseline='{4}'{5}{6}>{2}</text>"
                svg += svg_format_str.format(x, y, xml.sax.saxutils.escape(text), text_anchor, text_baseline, font_str,
                                             transform_str)
            elif command_id == "fillStyleGradient":
                command_var = command_args[0]
                defs += gradient_start + "".join(gradient_stops) + "</linearGradient>"
                fill_style = "url(#{0})".format("grad" + str(command_var))
            elif command_id == "fillStyle":
                fill_style = command_args[0]
            elif command_id == "font":
                font_style = None
                font_weight = None
                font_size = None
                font_family = None
                for font_part in [s for s in command_args[0].split(" ") if s]:
                    if font_part == "italic":
                        font_style = "italic"
                    elif font_part == "bold":
                        font_weight = "bold"
                    elif font_part.endswith("px") and int(font_part[0:-2]) > 0:
                        font_size = int(font_part[0:-2])
                    else:
                        font_family = font_part
            elif command_id == "textAlign":
                text_anchors = {"start": "start", "end": "end", "left": "start", "center": "middle", "right": "end"}
                text_anchor = text_anchors.get(command_args[0], "start")
            elif command_id == "textBaseline":
                text_baselines = {"top": "hanging", "hanging": "hanging", "middle": "middle",
                                  "alphabetic": "alphabetic", "ideaographic": "ideaographic", "bottom": "bottom"}
                text_baseline = text_baselines.get(command_args[0], "alphabetic")
            elif command_id == "strokeStyle":
                stroke_style = command_args[0]
            elif command_id == "lineWidth":
                line_width = command_args[0]
            elif command_id == "lineDash":
                line_dash = command_args[0]
            elif command_id == "lineCap":
                line_caps = {"square": "square", "round": "round", "butt": "butt"}
                line_cap = line_caps.get(command_args[0], "square")
            elif command_id == "lineJoin":
                line_joins = {"round": "round", "miter": "miter", "bevel": "bevel"}
                line_join = line_joins.get(command_args[0], "bevel")
            elif command_id == "gradient":
                # assumes that gradient will be used immediately after being
                # declared and stops being defined. this is currently enforced by
                # the way the commands are generated in drawing context.
                command_var, w, h, x1, y1, x2, y2 = command_args
                grad_id = "grad" + str(command_var)
                gradient_start = "<linearGradient id='{0}' x1='{1}' y1='{2}' x2='{3}' y2='{4}'>".format(grad_id,
                                                                                                        float(x1 / w),
                                                                                                        float(y1 / h),
                                                                                                        float(x2 / w),
                                                                                                        float(y2 / h))
            elif command_id == "colorStop":
                command_var, x, color = command_args
                gradient_stops.append("<stop offset='{0}%' stop-color='{1}' />".format(int(x * 100), color))
            else:
                logging.debug("Unknown command %s", command)
        xmlns = "xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'"
        viewbox_str = "{0} {1} {2} {3}".format(viewbox.left, viewbox.top, viewbox.width, viewbox.height)
        result = "<svg version='1.1' baseProfile='full' width='{0}' height='{1}' viewBox='{2}' {3}>".format(size.width,
                                                                                                            size.height,
                                                                                                            viewbox_str,
                                                                                                            xmlns)
        result += "<defs>" + defs + "</defs>"
        result += svg
        result += "</svg>"
        return result

    @contextmanager
    def saver(self):
        self.save()
        try:
            yield
        finally:
           self.restore()

    def save(self):
        self.commands.append(("save", ))
        self.save_count += 1

    def restore(self):
        self.commands.append(("restore", ))
        self.save_count -= 1

    def begin_path(self):
        self.commands.append(("beginPath", ))

    def close_path(self):
        self.commands.append(("closePath", ))

    def clip_rect(self, a, b, c, d):
        self.commands.append(("clip", float(a), float(b), float(c), float(d)))

    def translate(self, x, y):
        self.commands.append(("translate", float(x), float(y)))

    def scale(self, x, y):
        self.commands.append(("scale", float(x), float(y)))

    def rotate(self, radians):
        self.commands.append(("rotate", math.degrees(float(radians))))

    def move_to(self, x, y):
        self.commands.append(("moveTo", float(x), float(y)))

    def line_to(self, x, y):
        self.commands.append(("lineTo", float(x), float(y)))

    def rect(self, a, b, c, d):
        self.commands.append(("rect", float(a), float(b), float(c), float(d)))

    def round_rect(self, x, y, w, h, r):
        self.move_to(x + r, y)
        self.arc_to(x + w, y, x + w, y + h, r)
        self.arc_to(x + w, y + h, x, y + h, r)
        self.arc_to(x, y + h, x, y, r)
        self.arc_to(x, y, x + w, y, r)
        self.close_path()

    def arc(self, x, y, r, sa, ea, ac=False):
        self.commands.append(("arc", float(x), float(y), float(r), float(sa), float(ea), bool(ac)))

    def arc_to(self, x1, y1, x2, y2, r):
        self.commands.append(("arcTo", float(x1), float(y1), float(x2), float(y2), float(r)))

    def draw_image(self, img, a, b, c, d):
        # img should be rgba pack, uint32
        assert img.dtype == numpy.uint32
        with DrawingContext.__image_id_lock:
            DrawingContext.__image_id += 1
            image_id = DrawingContext.__image_id
        self.commands.append(
            ("image", img.shape[1], img.shape[0], img, int(image_id), float(a), float(b), float(c), float(d)))

    def stroke(self):
        self.commands.append(("stroke", ))

    def sleep(self, duration):
        self.commands.append(("sleep", duration))

    def mark_latency(self):
        self.commands.append(("latency", time.perf_counter()))

    def fill(self):
        self.commands.append(("fill", ))

    def fill_text(self, text, x, y, max_width=None):
        self.commands.append(("fillText", Unicode.u(text), float(x), float(y), float(max_width) if max_width else 0))

    @property
    def fill_style(self):
        raise NotImplementedError()

    @fill_style.setter
    def fill_style(self, a):
        if isinstance(a, DrawingContext.LinearGradient):
            self.commands.extend(a.commands)
            self.commands.append(("fillStyleGradient", int(a.command_var)))
        else:
            self.commands.append(("fillStyle", str(a)))

    @property
    def font(self):
        raise NotImplementedError()

    @font.setter
    def font(self, a):
        """
            Set the text font.

            Supports 'normal', 'bold', 'italic', size specific as '14px', and font-family.
        """
        self.commands.append(("font", str(a)))

    def __get_text_align(self):
        raise NotImplementedError()

    def __set_text_align(self, a):
        """
            Set text alignment.

            Valid values are 'start', 'end', 'left', 'center', 'right'. Default is 'start'.

            Default is 'start'.
        """
        self.commands.append(("textAlign", str(a)))

    text_align = property(__get_text_align, __set_text_align)

    def __get_text_baseline(self):
        raise NotImplementedError()

    def __set_text_baseline(self, a):
        """
            Set the text baseline.

            Valid values are 'top', 'hanging', 'middle', 'alphabetic', 'ideographic', and 'bottom'.

            Default is 'alphabetic'.
        """
        self.commands.append(("textBaseline", str(a)))

    text_baseline = property(__get_text_baseline, __set_text_baseline)

    def __get_stroke_style(self):
        raise NotImplementedError()

    def __set_stroke_style(self, a):
        self.commands.append(("strokeStyle", str(a)))

    stroke_style = property(__get_stroke_style, __set_stroke_style)

    def __get_line_width(self):
        raise NotImplementedError()

    def __set_line_width(self, a):
        self.commands.append(("lineWidth", float(a)))

    line_width = property(__get_line_width, __set_line_width)

    def __get_line_dash(self):
        raise NotImplementedError()

    def __set_line_dash(self, a):
        """ Set the line dash. Takes a single value with the length of the dash. """
        self.commands.append(("lineDash", float(a)))

    line_dash = property(__get_line_dash, __set_line_dash)

    def __get_line_cap(self):
        raise NotImplementedError()

    def __set_line_cap(self, a):
        """ Set the line join. Valid values are 'square', 'round', 'butt'. Default is 'square'. """
        self.commands.append(("lineCap", str(a)))

    line_cap = property(__get_line_cap, __set_line_cap)

    def __get_line_join(self):
        raise NotImplementedError()

    def __set_line_join(self, a):
        """ Set the line join. Valid values are 'round', 'miter', 'bevel'. Default is 'bevel'. """
        self.commands.append(("lineJoin", str(a)))

    line_join = property(__get_line_join, __set_line_join)

    class LinearGradient(object):
        next = 1

        def __init__(self, width, height, x1, y1, x2, y2):  # pylint: disable=invalid-name
            self.commands = []
            self.command_var = DrawingContext.LinearGradient.next
            self.commands.append(("gradient", self.command_var, float(width), float(height), float(x1), float(y1),
                                  float(x2), float(y2)))
            DrawingContext.LinearGradient.next += 1

        def add_color_stop(self, x, color):
            self.commands.append(("colorStop", self.command_var, float(x), str(color)))

    def create_linear_gradient(self, width, height, x1, y1, x2, y2):  # pylint: disable=invalid-name
        gradient = DrawingContext.LinearGradient(width, height, x1, y1, x2, y2)
        return gradient

    def statistics(self, stat_id):
        self.commands.append(("statistics", str(stat_id)))

    @contextmanager
    def layer(self, layer_id):
        self.begin_layer(layer_id)
        try:
            yield
        finally:
            self.end_layer(layer_id)

    def create_layer(self):
        if self.__storage is not None:
            return str(uuid.uuid4())
        return None

    def begin_layer(self, layer_id):
        if layer_id:
            self.__storage.begin_layer(self, layer_id)

    def end_layer(self, layer_id):
        if layer_id:
            self.__storage.end_layer(self, layer_id)

    def draw_layer(self, layer_id):
        self.__storage.draw_layer(self, layer_id)
