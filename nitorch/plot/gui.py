import math
import time
import torch
from nitorch import io
from nitorch import spatial
from nitorch.core import utils, py
from nitorch.core.optionals import try_import
from .volumes import show_orthogonal_slices
# from .menu import Menu, MenuItem

# optional imports
plt = try_import('matplotlib.pyplot', _as=True)
gridspec = try_import('matplotlib.gridspec', _as=True)


__all__ = ['ImageViewer']


def ordered_set(*values):
    return tuple({v: None for v in values}.keys())


class ImageArtist:

    def __init__(self, image, parent=None, **kwargs):

        self.parent = parent
        self.show_cursor = kwargs.pop('show_cursor', getattr(self.parent,'show_cursor', True))
        self.equalize = kwargs.pop('equalize', getattr(self.parent, 'equalize', False))
        self.mode = kwargs.pop('mode', getattr(self.parent, 'mode', 'intensity'))
        self.interpolation = kwargs.pop('interpolation', getattr(self.parent, 'interpolation', 1))
        self.colormap = kwargs.pop('colormap', getattr(self.parent, 'colormap', None))
        self.mmap = kwargs.pop('mmap', getattr(self.parent, 'mmap', False))
        self.layout = kwargs.pop('layout', getattr(self.parent, 'layout', 'orth'))

        for k, v in kwargs.items():
            setattr(self, k, v)
        self.image = image

    @property
    def image(self):
        return self._image

    @image.setter
    def image(self, value):
        self._image = value
        self._map_image()

    @property
    def affine(self):
        return getattr(self, '_affine', None)

    @affine.setter
    def affine(self, value):
        if value is None:
            self._affine = spatial.affine_default(self.shape)
        self._affine = value

    @property
    def shape(self):
        return getattr(self, '_shape', None)

    @property
    def map(self):
        return getattr(self, '_map', None)

    @property
    def fdata(self):
        if getattr(self, '_fdata', None) is None:
            if self.map is not None:
                if self.mmap:
                    return self.map.fdata()
                else:
                    self._fdata = self.map.fdata()
        return getattr(self, '_fdata', None)

    def _map_image(self):
        image = self.image
        self._map = None
        self._fdata = None
        self._affine = None
        self._shape = None
        if isinstance(image, str):
            self._map = io.map(image)
        else:
            self._map = None

        if self._map is None:
            if not isinstance(image, (list, tuple)):
                image = [image]
            if len(image) < 2:
                image = [*image, None, None]
            dat, aff, *_ = image
            dat = torch.as_tensor(dat)
            if aff is None:
                aff = spatial.affine_default(dat.shape[-3:])
            self._fdata = dat
            self._affine = aff
            self._shape = tuple(dat.shape[-3:])
        else:
            self._affine = self._map.affine
            self._shape = tuple(self._map.shape[-3:])

    def load(self):
        if self.fdata is None and self.map is not None:
            self._fdata = self.map.fdata(device=self.device)
        return self.fdata

    def clear(self):
        if self.fdata is not None and self.map is not None:
            self._fdata = None

    @property
    def mmap(self):
        return self._mmap

    @mmap.setter
    def mmap(self, value):
        self._mmap = bool(value)
        if self.mmap and self._fdata is not None:
            self._fdata = None

    @property
    def device(self):
        return getattr(self, '_device', None)

    @device.setter
    def device(self, value):
        if isinstance(value, int):
            value = f'cuda:{value}'
        self._device = torch.device(value)
        if self._fdata is not None:
            self._fdata = self._fdata.to(self.device)

    @property
    def clim(self):
        return getattr(self, '_cmin', None), getattr(self, '_cmax', None)

    @clim.setter
    def clim(self, value):
        if torch.is_tensor(value):
            value = value.flatten().unbind()
        cmin, cmax = py.make_list(value, 2)
        self._cmin = cmin
        self._cmax = cmax

    def set_show_cursor(self, value, all=False):
        self.show_cursor = value
        if all:
            self.propagate('show_cursor')

    def set_equalize(self, value, all=False):
        self.equalize = value
        if all:
            self.propagate('equalize')

    def set_mode(self, value, all=False):
        self.mode = value
        if all:
            self.propagate('mode')

    def set_interpolation(self, value, all=False):
        self.interpolation = value
        if all:
            self.propagate('interpolation')

    def set_colormap(self, value, all=False):
        self.colormap = value
        if all:
            self.propagate('colormap')

    def set_mmap(self, value, all=False):
        self.mmap = value
        if all:
            self.propagate('mmap')

    def set_layout(self, value, all=False):
        self.layout = value
        if all:
            self.propagate('layout')

    def set_device(self, value, all=False):
        self.device = value
        if all:
            self.propagate('device')

    def set_clim(self, value, all=False):
        self.clim = value
        if all:
            self.propagate('clim')

    def propagate(self, key):
        for image in getattr(self.parent, 'images', []):
            if image is not self:
                setattr(image, key, getattr(self, key))

    def draw(self, index=None, space=None, fov=None, fig=None, gs=None):
        fig = fig or getattr(self.parent, 'fig')
        fig = (fig, gs)

        _, self._axes, self._mats = show_orthogonal_slices(
            self.fdata, index, self.affine,
            fig=fig,
            layout=self.layout,
            interpolation=self.interpolation,
            colormap=self.colormap,
            eq=self.equalize,
            clim=self.clim,
            show_cursor=self.show_cursor,
            space=space,
            bbox=fov,
            return_mat=True)


class ImageViewer:
    """Interactive viewer for volumetric images.

    Attributes
    ----------
    auto_redraw : bool, default=False
        Automatically update the viewer when an attribute changes.
    dpi : int, default=72
        Resolution of the viewer (pixels per inch)
    size : (width: float, height: float),
        Size of the figure
    aspect : float
        Width/Height
    fig : int or plt.Figure
        Figure object
    images : tuple[str or (tensor, tensor) or ImageArtist]
        List of filenames or (data, affine).
        At assignment, they are converted to ImageArtist objects.
    grid : (nrow: int or None, ncol: int or None) or None, default=None
        Grid shape used to display images.
        If None, an optimal shape is found based on the figure size,
        image layout and number of images.
    space : (4, 4) tensor
        Orientation matrix of the visualisation space.
        By default, stadard RAS space
    index : tuple[float]
        Cursor position in millimetric visualisation space.
    fov : (min: tuple[float], max: tuple[float])
        Minimum and maximum coordinates of the field of view in
        millimetric visualisation space.
        If None, use the maximum bounding box of all images.
    fov_size : float or tuple[float]
        Size of the field of view.
        If None, use the maximum bounding box of all images.
        After assignment, the center of th eFOv is the current
        cursor position.
    layout : {'row', 'col', 'orth'}, default='orth'
        Layout of the three views.
    show_cursor : bool, default=True
        Show cross-hair.
    equalize : float or {'lin', 'quad', 'log'}, default=None
        Histogram equalization method.
    interpolation : int, default=1
        Interpolation order.
    colormap : str or (N, 3) tensor
        Mapping from intensity to color.
    mmap : bool, default=False
        If True, do not keep the full images in memory but reload
        them each time the figure is redrawn. Slower but saves memory.
    scroll_step : float, default=100
        Amount of zoom corresponding to one scroll unit.
    draw_freq : float, default=1/25
        Minimum amount of time, in sec, between two calls to `redraw`.
        If `redraw` is called more than twice within `draw_freq` sec, only
        the first call is executed.

    """

    def __init__(self, images, **kwargs):
        """

        Parameters
        ----------
        images : list[str or (tensor, tensor)]
            Inputs images.

        Other Parameters
        ----------------
        All attributes can be set on build.
        """

        if plt is None:
            raise ImportError('Matplotlib not available')

        # defaults
        dpi = kwargs.pop('dpi', None)
        size = kwargs.pop('size', None)
        fig = kwargs.pop('fig', None) or plt.figure(figsize=size, dpi=dpi)
        if isinstance(fig, int):
            fig = plt.figure(fig)
        self.fig = fig

        self.images = images
        self.grid = kwargs.pop('grid', None)
        self.space = kwargs.pop('space', None)
        self.fov = kwargs.pop('fov', None)
        self.index = kwargs.pop('index', None)

        # user-defined
        for k, v in kwargs.items():
            setattr(self, k, v)

        fig.canvas.mpl_connect('button_press_event', self.on_press)
        fig.canvas.mpl_connect('motion_notify_event', self.on_move)
        fig.canvas.mpl_connect('button_release_event', self.on_release)
        fig.canvas.mpl_connect('scroll_event', self.on_scroll)
        fig.canvas.mpl_connect('resize_event', self.on_resize)
        self.redraw(show=True)

        # self.menu = Menu(self.fig,
        #                  [MenuItem(self.fig, 'field of view'),
        #                   MenuItem(self.fig, 'show cursor'),
        #                   MenuItem(self.fig, 'equalize'),
        #                   MenuItem(self.fig, 'interpolation'),])
        # self.fig.add_artist(self.menu)

    def __setattr__(self, key, value):
        do_redraw = key[0] != '_' and self.auto_redraw
        super().__setattr__(key, value)
        if do_redraw:
            self.redraw()

    def _image_from_ax(self, ax):
        for image in self.images:
            for d, ax0 in enumerate(image._axes):
                if ax is ax0:
                    return image, d
        return None, None

    def _index_from_cursor(self, x, y, image, n_ax):
        p = utils.as_tensor([x, y, 0])
        mat = image._mats[n_ax]
        self.index = spatial.affine_matvec(mat, p)

    def on_release(self, event):
        if event.button == 1:  # LEFT
            self._is_pressed = False

    def on_press(self, event):
        if event.button == 1:  # LEFT
            self._is_pressed = True
            if event.inaxes:
                x, y = (event.xdata, event.ydata)
                image, n_ax = self._image_from_ax(event.inaxes)
                self._index_from_cursor(x, y, image, n_ax)
                self.redraw(show=True)

    def on_move(self, event):
        is_pressed = getattr(self, '_is_pressed', False)
        if is_pressed and event.inaxes:
            x, y = (event.xdata, event.ydata)
            image, n_ax = self._image_from_ax(event.inaxes)
            self._index_from_cursor(x, y, image, n_ax)
            self.redraw(show=True)

    def on_resize(self, event):
        self.redraw(show=True)

    def on_scroll(self, event):
        auto, self.auto_redraw = (self.auto_redraw, False)
        index0 = self.index
        if event.inaxes:
            x, y = (event.xdata, event.ydata)
            image, n_ax = self._image_from_ax(event.inaxes)
            if image:
                self._index_from_cursor(x, y, image, n_ax)
        steps = event.step
        step_size = self.scroll_step ** (-steps)
        min, max = self.fov
        new_min = [i - step_size * (i - mn0) for i, mn0 in zip(self.index, min)]
        new_max = [mn + step_size * (mx0 - mn0)
                   for i, mn, mn0, mx0 in zip(self.index, new_min, min, max)]
        self.fov = (new_min, new_max)
        self.index = index0
        self.redraw(show=True)
        self.auto_redraw = auto

    @property
    def auto_redraw(self):
        return getattr(self, '_auto_redraw', False)

    @auto_redraw.setter
    def auto_redraw(self, value):
        self._auto_redraw = bool(value)

    @property
    def dpi(self):
        """pixels per inch"""
        return self.fig.get_dpi()

    @dpi.setter
    def dpi(self, value):
        if not isinstance(value, (int, float)):
            raise TypeError('Expected a number')
        self.fig.set_dpi(float(value))

    @property
    def aspect(self):
        """Width/Height"""
        return self.size[0]/self.size[1]

    @aspect.setter
    def aspect(self, value):
        """Change aspect while keeping area untouched"""
        if not isinstance(value, (int, float)):
            raise TypeError('Expected a number')
        s0, s1 = self.size
        area = math.sqrt(s0*s1)
        s0 = math.sqrt(area * value)
        s1 = math.sqrt(area / value)
        self.size = (s0, s1)

    @property
    def scroll_step(self):
        """(Width, Height)"""
        return getattr(self, '_scroll_step', 100)

    @scroll_step.setter
    def scroll_step(self, value):
        if not isinstance(value, (float, int)):
            raise ValueError('Expected a float')
        self._scroll_step = value

    @property
    def draw_freq(self):
        """(Width, Height)"""
        return getattr(self, '_draw_freq', 1/25)

    @draw_freq.setter
    def draw_freq(self, value):
        if not isinstance(value, (float, int)):
            raise ValueError('Expected a float')
        self._draw_freq = value

    @property
    def size(self):
        """(Width, Height)"""
        return tuple(self.fig.get_size_inches())

    @size.setter
    def size(self, value):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError('Expected a tuple of two values')
        self.fig.get_size_inches(*value)

    @property
    def images(self):
        return tuple(self._images)

    @images.setter
    def images(self, value):
        self._images = [ImageArtist(image, parent=self) for image in value]

    @property
    def mmap(self):
        mmap = [image.mmap for image in self.images]
        return ordered_set(*mmap)[0]

    @mmap.setter
    def mmap(self, value):
        for image in self.images:
            image.mmap = bool(value)

    @property
    def device(self):
        device = [image.device for image in self.images]
        return ordered_set(*device)[0]

    @device.setter
    def device(self, value):
        for image in self.images:
            image.device = value

    @property
    def layout(self):
        layout = [image.layout for image in self.images]
        return ordered_set(*layout)[0]

    @layout.setter
    def layout(self, value):
        value = value.lower()
        if value not in ('row', 'col', 'orth'):
            raise ValueError(f"Expected on of 'row', 'col', 'orth' but "
                             f"got {value}")
        for image in self.images:
            image.layout = value

    @property
    def show_cursor(self):
        show_cursor = [image.show_cursor for image in self.images]
        return ordered_set(*show_cursor)[0]

    @show_cursor.setter
    def show_cursor(self, value):
        if not isinstance(value, bool):
            value = float(value)
        for image in self.images:
            image.show_cursor = value

    @property
    def equalize(self):
        equalize = [image.equalize for image in self.images]
        return ordered_set(*equalize)[0]

    @equalize.setter
    def equalize(self, value):
        if not isinstance(value, str):
            value = float(value)
        else:
            value = value.lower()
            if value not in ('lin', 'linear',
                             'quad', 'quadratic',
                             'log', 'logarithmic'):
                raise ValueError(f'Unknown equalization {value}')
        for image in self.images:
            image.equalize = value

    @property
    def clim(self):
        clim = [image.clim for image in self.images]
        return (ordered_set(*[c[0] for c in clim])[0],
                ordered_set(*[c[1] for c in clim])[0])

    @clim.setter
    def clim(self, value):
        for image in self.images:
            image.clim = value

    @property
    def mode(self):
        mode = [image.mode for image in self.images]
        return ordered_set(*mode)[0]

    @mode.setter
    def mode(self, value):
        value = value.lower()
        if value not in ('int', 'intensity',
                         'cat', 'categorical',
                         'disp', 'displacement'):
            raise ValueError(f'Unknown mode {value}')
        for image in self.images:
            image.mode = value

    @property
    def interpolation(self):
        interpolation = [image.interpolation for image in self.images]
        return ordered_set(*interpolation)[0]

    @interpolation.setter
    def interpolation(self, value):
        if not isinstance(value, str):
            value = int(value)
        else:
            value = value.lower()
        for image in self.images:
            image.interpolation = value

    @property
    def colormap(self):
        colormap = [image.colormap for image in self.images
                    if not torch.is_tensor(image.colormap)]
        if not colormap:
            return self.images[0].colormap
        else:
            return ordered_set(*colormap)[0]

    @colormap.setter
    def colormap(self, value):
        if not isinstance(value, str):
            value = torch.as_tensor(value)
        for image in self.images:
            image.colormap = value

    @property
    def index(self):
        return self._index

    @index.setter
    def index(self, value):
        if torch.is_tensor(value):
            value = value.flatten().tolist()
        value = py.make_list(value, 3)
        value = [(mx+mn)/2 if v is None else v
                 for v, mn, mx in zip(value, *self.fov)]
        self._index = tuple(value)

    @property
    def fov(self):
        return self._fov

    @fov.setter
    def fov(self, value):
        if value is None:
            value = (None, None)
        min, max = value
        if torch.is_tensor(min):
            min = min.flatten().tolist()
        min = py.make_list(min, 3)
        if torch.is_tensor(max):
            max = max.flatten().tolist()
        max = py.make_list(max, 3)
        if any(mn is None for mn in min) or any(mx is None for mx in max):
            min0, max0 = self._max_fov()
            min = [mn or mn0 for mn, mn0 in zip(min, min0)]
            max = [mx or mx0 for mx, mx0 in zip(max, max0)]
        self._fov = (tuple(min), tuple(max))

    def _max_fov(self):
        affines = [image.affine for image in self.images]
        shapes = [image.shape for image in self.images]
        affines = utils.as_tensor(affines)
        shapes = utils.as_tensor(shapes)
        return spatial.compute_fov(self._space_matrix, affines, shapes)

    @property
    def fov_size(self):
        min, max = self.fov
        return tuple(mx-mn for mx, mn in zip(max, min))

    @fov_size.setter
    def fov_size(self, value):
        if torch.is_tensor(value):
            value = value.flatten().tolist()
        value = py.make_list(value, 3)
        min = [i - v/2 if v else None for i, v in zip(self._index, value)]
        max = [i + v/2 if v else None for i, v in zip(self._index, value)]
        self.fov = [min, max]

    @property
    def space(self):
        return self._space

    @space.setter
    def space(self, value):
        self._space = value
        if torch.is_tensor(value):
            if value.shape != (4, 4):
                raise ValueError('Expected 4x4 matrix')
            self._space_matrix = value
        elif isinstance(value, int):
            affines = [image.affine for image in self.images]
            self._space_matrix = affines[value]
        else:
            if value is not None:
                raise ValueError('Expected a 4x4 matrix or an int or None')
            affines = [image.affine for image in self.images]
            voxel_size = spatial.voxel_size(utils.as_tensor(affines))
            voxel_size = voxel_size.min()
            self._space_matrix = torch.eye(4)
            self._space_matrix[:-1, :-1] *= voxel_size

    @property
    def grid(self):
        return self._grid

    @grid.setter
    def grid(self, value):
        if value is None:
            self._grid = (None, None)
        else:
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError('Expected a tuple of two integers')
            gx, gy = value
            if gx is not None and gy is not None and gx*gy != len(self.images):
                raise ValueError('Grid size not consistant with number '
                                 'of images')
            self._grid = tuple(value)

    def _grid_auto(self, nb_image):
        gx, gy = self._grid
        if gx is not None and gy is not None:
            return gx, gy
        if gx is None and gy is not None:
            gx = int(math.ceil(nb_image / gy))
            return gx, gy
        if gy is None and gx is not None:
            gy = int(math.ceil(nb_image / gx))
            return gx, gy
        # heuristic
        if self.layout == 'row':
            ratio = [1, 3]
        elif self.layout == 'col':
            ratio = [3, 1]
        else:
            assert self.layout == 'orth', self.layout
            ratio = [2, 2]
        rh, rw = ratio
        aspect = self.aspect  # width / height
        best_empty = None
        best_size = (None, None)
        for n_rows in range(1, nb_image + 1):
            n_cols = math.ceil(nb_image / n_rows)
            nr = n_rows * rh
            nc = n_cols * rw
            inner_aspect = nc / nr
            inner_area = nc * nr
            if inner_aspect < aspect:
                outer_area = nr * nr * aspect
            else:
                outer_area = nc * nc / aspect
            empty_ratio = (outer_area - inner_area) / outer_area
            empty_box = (n_rows*n_cols - nb_image) * (rh * rw) / outer_area
            compactness = 0.01 * (max(nr, nc)/min(nr, nc) - 1)
            empty = empty_box + empty_ratio + compactness
            # print(f'{n_rows} {n_cols} | {empty_box:6.3f} {empty_ratio:6.3f} {compactness:6.3f} {inner_aspect:6.3f}')
            if best_empty is None or empty < best_empty:
                best_size = (n_rows, n_cols)
                best_empty = empty
        return best_size

    def redraw(self, show=False):

        last_draw = getattr(self, '_last_draw', 0)
        if (time.time() - last_draw) < self.draw_freq:
            return

        self.fig.clear()

        grid = self._grid_auto(len(self.images))
        gs = gridspec.GridSpec(*grid)

        for d, image in enumerate(self.images):
            image.draw(index=self.index, space=self._space_matrix,
                       fov=self.fov, fig=self.fig, gs=gs[d])

        if show:
            self.fig.show()

        self._last_draw = time.time()



