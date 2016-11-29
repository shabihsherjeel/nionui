"""
    Grid of thumbnails.

    TODO: GridCanvasItem should handle dragging multiple items
    TODO: GridCanvasItem should handle keyboard navigation
    TODO: GridCanvasItem should allow drag selection to select multiple
"""

# futures
from __future__ import absolute_import
from __future__ import division

# standard libraries
# none

# third party libraries
# none

# local libraries
from . import CanvasItem
from nion.utils import Geometry


class GridCanvasItem(CanvasItem.AbstractCanvasItem):
    """
    Takes a delegate that supports the following properties, methods, and optional methods:

    Properties:
        item_count: the number of items to be displayed

    Methods:
        paint_item(drawing_context, index, rect, is_selected): paint the cell for index at the position

    Optional methods:
        on_content_menu_event(index, x, y, gx, gy): called when user wants context menu for given index
        on_delete_pressed(): called when user presses delete key
        on_drag_started(index, x, y, modifiers): called when user begins drag with given index
    """

    def __init__(self, delegate, selection):
        super().__init__()
        # store parameters
        self.__delegate = delegate
        self.__selection = selection
        self.__selection_changed_listener = self.__selection.changed_event.listen(self.update)
        # configure super
        self.wants_mouse_events = True
        self.focusable = True
        # internal variables
        self.__mouse_pressed = False
        self.__mouse_index = None
        self.__mouse_position = None
        self.__mouse_dragging = False

    def close(self):
        self.__selection_changed_listener.close()
        self.__selection_changed_listener = None
        super().close()

    def detach_delegate(self):
        self.__delegate = None

    def update_layout(self, canvas_origin, canvas_size, trigger_update=True):
        """Override from abstract canvas item.

        Adjust the canvas height based on the constraints.
        """
        canvas_size = Geometry.IntSize.make(canvas_size)
        canvas_size = Geometry.IntSize(height=self.__calculate_layout_height(canvas_size),
                                       width=canvas_size.width)
        super().update_layout(canvas_origin, canvas_size, trigger_update)

    def wheel_changed(self, x, y, dx, dy, is_horizontal):
        dy = dy if not is_horizontal else 0.0
        new_canvas_origin = Geometry.IntPoint.make(self.canvas_origin) + Geometry.IntPoint(x=0, y=dy)
        self.update_layout(new_canvas_origin, self.canvas_size)
        self.update()
        return True

    def __calculate_item_size(self, canvas_size: Geometry.IntSize) -> Geometry.IntSize:
        target_size = 80
        item_width = int(canvas_size.width / (((canvas_size.width + target_size // 4) // target_size)))
        return Geometry.IntSize(item_width, item_width)

    def __calculate_layout_height(self, canvas_size: Geometry.IntSize) -> int:
        item_size = self.__calculate_item_size(canvas_size)
        items_per_row = int(canvas_size.width / item_size.width)
        item_count = self.__delegate.item_count if self.__delegate else 0
        item_rows = (item_count + items_per_row - 1) // items_per_row
        return item_rows * item_size.height

    def __rect_for_index(self, index: int) -> Geometry.IntRect:
        canvas_size = self.canvas_size
        item_size = self.__calculate_item_size(canvas_size)
        items_per_row = int(canvas_size.width / item_size.width)
        row = index // items_per_row
        column = index - row * items_per_row
        return Geometry.IntRect(origin=Geometry.IntPoint(y=row * item_size.height, x=column * item_size.width),
                                size=Geometry.IntSize(width=item_size.width, height=item_size.height))

    def update(self):
        if self.canvas_origin is not None and self.canvas_size is not None:
            if self.__calculate_layout_height(self.canvas_size) != self.canvas_size.height:
                self.refresh_layout()
        super().update()

    def _repaint_visible(self, drawing_context, visible_rect):
        if self.__delegate:
            canvas_size = self.canvas_size
            item_size = self.__calculate_item_size(canvas_size)
            items_per_row = int(canvas_size.width / item_size.width)

            with drawing_context.saver():
                max_index = self.__delegate.item_count
                top_visible_row = visible_rect.top // item_size.height
                bottom_visible_row = visible_rect.bottom // item_size.height
                for row in range(top_visible_row, bottom_visible_row + 1):
                    for column in range(items_per_row):
                        index = row * items_per_row + column
                        if index < max_index:
                            rect = Geometry.IntRect(origin=Geometry.IntPoint(y=row * item_size.height, x=column * item_size.width),
                                                    size=Geometry.IntSize(width=item_size.width, height=item_size.height))
                            if rect.intersects_rect(visible_rect):
                                is_selected = self.__selection.contains(index)
                                if is_selected:
                                    drawing_context.save()
                                    drawing_context.begin_path()
                                    drawing_context.rect(rect.left, rect.top, rect.width, rect.height)
                                    drawing_context.fill_style = "#3875D6" if self.focused else "#BBB"
                                    drawing_context.fill()
                                    drawing_context.restore()
                                self.__delegate.paint_item(drawing_context, index, rect, is_selected)

    def _repaint(self, drawing_context):
        self._repaint_visible(drawing_context, self.canvas_bounds)

    def context_menu_event(self, x, y, gx, gy):
        if self.__delegate:
            mouse_index = self.__get_item_index_at(x, y)
            max_index = self.__delegate.item_count
            if mouse_index >= 0 and mouse_index < max_index:
                if not self.__selection.contains(mouse_index):
                    self.__selection.set(mouse_index)
                if self.__delegate.on_context_menu_event:
                    return self.__delegate.on_context_menu_event(mouse_index, x, y, gx, gy)
            else:
                if self.__delegate.on_context_menu_event:
                    return self.__delegate.on_context_menu_event(None, x, y, gx, gy)
        return False

    def __get_item_index_at(self, x, y):
        canvas_size = self.canvas_size
        item_size = self.__calculate_item_size(canvas_size)
        items_per_row = int(canvas_size.width / item_size.width)
        mouse_row = y // item_size.height
        mouse_column = x // item_size.width
        mouse_index = mouse_row * items_per_row + mouse_column
        return mouse_index

    def mouse_pressed(self, x, y, modifiers):
        if self.__delegate:
            mouse_index = self.__get_item_index_at(x, y)
            max_index = self.__delegate.item_count
            if mouse_index >= 0 and mouse_index < max_index:
                self.__mouse_index = mouse_index
                if not modifiers.shift and not modifiers.control:
                    self.__mouse_pressed = True
                    self.__mouse_position = Geometry.IntPoint(y=y, x=x)
                return True
            return super().mouse_pressed(x, y, modifiers)

    def mouse_released(self, x, y, modifiers):
        if self.__delegate and self.__mouse_pressed:
            # double check whether mouse_released has been called explicitly as part of a drag.
            # see https://bugreports.qt.io/browse/QTBUG-40733
            mouse_index = self.__mouse_index
            max_index = self.__delegate.item_count
            if mouse_index is not None and mouse_index >= 0 and mouse_index < max_index:
                if modifiers.shift:
                    self.__selection.extend(mouse_index)
                elif modifiers.control:
                    self.__selection.toggle(mouse_index)
                else:
                    self.__selection.set(mouse_index)
        self.__mouse_pressed = False
        self.__mouse_index = None
        self.__mouse_position = None
        self.__mouse_dragging = False
        return True

    def mouse_position_changed(self, x, y, modifiers):
        if self.__mouse_pressed:
            if not self.__mouse_dragging and Geometry.distance(self.__mouse_position, Geometry.IntPoint(y=y, x=x)) > 8:
                self.__mouse_dragging = True
                if self.__delegate and self.__delegate.on_drag_started:
                    self.root_container.bypass_request_focus()
                    self.__delegate.on_drag_started(self.__mouse_index, x, y, modifiers)
                    # once a drag starts, mouse release will not be called; call it here instead
                    self.mouse_released(x, y, modifiers)
                return True
        return super().mouse_position_changed(x, y, modifiers)

    def __make_selection_visible(self, top):
        if self.__delegate:
            selected_indexes = list(self.__selection.indexes)
            if len(selected_indexes) > 0:
                min_index = min(selected_indexes)
                max_index = max(selected_indexes)
                min_rect = self.__rect_for_index(min_index)
                max_rect = self.__rect_for_index(max_index)
                visible_rect = self.container.visible_rect
                if top:
                    if min_rect.top < visible_rect.top:
                        self.update_layout(Geometry.IntPoint(y=-min_rect.top, x=self.canvas_origin.x), self.canvas_size)
                    elif min_rect.bottom > visible_rect.bottom:
                        self.update_layout(Geometry.IntPoint(y=-min_rect.bottom + visible_rect.height, x=self.canvas_origin.x), self.canvas_size)
                else:
                    if max_rect.bottom > visible_rect.bottom:
                        self.update_layout(Geometry.IntPoint(y=-max_rect.bottom + visible_rect.height, x=self.canvas_origin.x), self.canvas_size)
                    elif max_rect.top < visible_rect.top:
                        self.update_layout(Geometry.IntPoint(y=-max_rect.top, x=self.canvas_origin.x), self.canvas_size)

    def make_selection_visible(self):
        self.__make_selection_visible(True)

    def key_pressed(self, key):
        canvas_size = self.canvas_size
        item_size = self.__calculate_item_size(canvas_size)
        if self.__delegate:
            if key.is_delete:
                if self.__delegate.on_delete_pressed:
                    self.__delegate.on_delete_pressed()
                return True
            if key.is_up_arrow:
                new_index = None
                items_per_row = int(canvas_size.width / item_size.width)
                indexes = self.__selection.indexes
                if len(indexes) > 0:
                    new_index = max(min(indexes) - items_per_row, 0)
                elif self.__delegate.item_count > 0:
                    new_index = self.__delegate.item_count - 1
                if new_index is not None:
                    if key.modifiers.shift:
                        self.__selection.extend(new_index)
                    else:
                        self.__selection.set(new_index)
                self.__make_selection_visible(top=True)
                return True
            if key.is_down_arrow:
                new_index = None
                items_per_row = int(canvas_size.width / item_size.width)
                indexes = self.__selection.indexes
                if len(indexes) > 0:
                    new_index = min(max(indexes) + items_per_row, self.__delegate.item_count - 1)
                elif self.__delegate.item_count > 0:
                    new_index = 0
                if new_index is not None:
                    if key.modifiers.shift:
                        self.__selection.extend(new_index)
                    else:
                        self.__selection.set(new_index)
                self.__make_selection_visible(top=False)
                return True
            if key.is_left_arrow:
                new_index = None
                indexes = self.__selection.indexes
                if len(indexes) > 0:
                    new_index = max(min(indexes) - 1, 0)
                elif self.__delegate.item_count > 0:
                    new_index = self.__delegate.item_count - 1
                if new_index is not None:
                    if key.modifiers.shift:
                        self.__selection.extend(new_index)
                    else:
                        self.__selection.set(new_index)
                self.__make_selection_visible(top=True)
                return True
            if key.is_right_arrow:
                new_index = None
                indexes = self.__selection.indexes
                if len(indexes) > 0:
                    new_index = min(max(indexes) + 1, self.__delegate.item_count - 1)
                elif self.__delegate.item_count > 0:
                    new_index = 0
                if new_index is not None:
                    if key.modifiers.shift:
                        self.__selection.extend(new_index)
                    else:
                        self.__selection.set(new_index)
                self.__make_selection_visible(top=False)
                return True
        return super().key_pressed(key)

    def handle_select_all(self):
        if self.__delegate:
            self.__selection.set_multiple(set(range(self.__delegate.item_count)))
            return True
        return False

    def handle_delete(self):
        if self.__delegate.on_delete_pressed:
            self.__delegate.on_delete_pressed()
        return True
