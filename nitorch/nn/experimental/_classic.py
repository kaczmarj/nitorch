import torch
from torch import nn
from torch.autograd import Variable
from nitorch import core, spatial, io
from nitorch import nn as nni


def prepare(inputs, device=None):

    def prepare_one(inp):
        if isinstance(inp, (list, tuple)):
            has_aff = len(inp) > 1
            if has_aff:
                aff0 = inp[1]
            inp, aff = prepare_one(inp[0])
            if has_aff:
                aff = aff0
            return inp, aff
        if isinstance(inp, str):
            inp = io.map(inp)
        if isinstance(inp, io.MappedArray):
            return inp.fdata(rand=True), inp.affine
        inp = torch.as_tensor(inp)
        aff = spatial.affine_default(inp.shape)
        return [inp, aff]

    prepared = []
    for inp in inputs:
        prepared.append(prepare_one(inp))

    prepared[0][0] = prepared[0][0].to(device=device, dtype=torch.float32)
    device = prepared[0][0].device
    dtype = prepared[0][0].dtype
    backend = dict(dtype=dtype, device=device)
    for i in range(len(prepared)):
        prepared[i][0] = prepared[i][0].to(**backend)
        prepared[i][1] = prepared[i][1].to(**backend)
    return prepared


def get_backend(tensor):
    device = tensor.device
    dtype = tensor.dtype
    return dict(dtype=dtype, device=device)


def affine(source, target, group='SE', loss=None, optim=None,
           interpolation='linear', bound='dct2', extrapolate=False,
           max_iter=1000, tolerance=1e-5, device=None, origin='center',
           init=None):
    """

    Parameters
    ----------
    source : path or tensor or (tensor, affine)
    target : path or tensor or (tensor, affine)
    group : {'T', 'SO', 'SE', 'CSO', 'GL+', 'Aff+'}, default='SE'
    loss : Loss, default=MutualInfoLoss()
    interpolation : int, default=1
    bound : bound_like, default='dct2'
    extrapolate : bool, default=False
    max_iter : int, default=1000
    tolerance : float, default=1e-5
    device : device, optional
    origin : {'native', 'center'}, default='center'

    Returns
    -------
    aff : (D+1, D+1) tensor
        Affine transformation matrix.
        The source affine matrix can be "corrected" by left-multiplying
        it with `aff`.
    moved : tensor
        Source image moved to target space.


    """
    # prepare all data tensors
    ((source, source_aff), (target, target_aff)) = prepare([source, target], device)
    backend = get_backend(source)
    dim = source.dim()

    # Rescale to [0, 1]
    source_min = source.min()
    source_max = source.max()
    target_min = target.min()
    target_max = target.max()
    source -= source_min
    source /= source_max - source_min
    target -= target_min
    target /= target_max - target_min

    # Shift origin
    if origin == 'center':
        shift = torch.as_tensor(target.shape, **backend)/2
        shift = -spatial.affine_matvec(target_aff, shift)
        target_aff[:-1, -1] += shift
        source_aff[:-1, -1] += shift

    # Prepare affine utils + Initialize parameters
    basis = spatial.affine_basis(group, dim, **backend)
    nb_prm = spatial.affine_basis_size(group, dim)
    if init is not None:
        parameters = torch.as_tensor(init, **backend)
        parameters = parameters.reshape(nb_prm)
    else:
        parameters = torch.zeros(nb_prm, **backend)
    parameters = Variable(parameters, requires_grad=True)
    identity = spatial.identity_grid(target.shape, **backend)

    def pull(q):
        aff = core.linalg.expm(q, basis)
        aff = spatial.affine_matmul(aff, target_aff)
        aff = spatial.affine_lmdiv(source_aff, aff)
        grid = spatial.affine_matvec(aff, identity)
        moved = spatial.grid_pull(source[None, None, ...], grid[None, ...],
                                  interpolation=interpolation, bound=bound,
                                  extrapolate=extrapolate)[0, 0]
        return moved

    # Prepare loss and optimizer
    if loss is None:
        loss_fn = nni.MutualInfoLoss()
        loss = lambda x, y: loss_fn(x[None, None, ...], y[None, None, ...])

    if optim is None:
        optim = torch.optim.Adam
    optim = optim([parameters], lr=1e-4)

    # Optim loop
    loss_val = core.constants.inf
    for n_iter in range(max_iter):

        loss_val0 = loss_val
        moved = pull(parameters)
        loss_val = loss(moved, target)
        loss_val.backward()
        optim.step()

        with torch.no_grad():
            crit = (loss_val0 - loss_val)
            if n_iter % 10 == 0:
                print('{:4d} {:12.6f} ({:12.6g})'
                      .format(n_iter, loss_val.item(), crit.item()), 
                      end='\r')
            if crit.abs() < tolerance:
                break

    print('')
    with torch.no_grad():
        moved = pull(parameters)
        aff = core.linalg.expm(parameters, basis)
        if origin == 'center':
            aff[:-1, -1] -= shift
            shift = core.linalg.matvec(aff[:-1, :-1], shift)
            aff[:-1, -1] += shift
        aff = aff.inverse()
        aff.requires_grad_(False)
        return aff, moved


def diffeo(source, target, group='SE', image_loss=None, vel_loss=None,
           interpolation='linear', bound='dct2', extrapolate=False,
           max_iter=1000, tolerance=1e-5, device=None, origin='center',
           init=None):
    """

    Parameters
    ----------
    source : path or tensor or (tensor, affine)
    target : path or tensor or (tensor, affine)
    group : {'T', 'SO', 'SE', 'CSO', 'GL+', 'Aff+'}, default='SE'
    loss : Loss, default=MutualInfoLoss()
    interpolation : int, default=1
    bound : bound_like, default='dct2'
    extrapolate : bool, default=False
    max_iter : int, default=1000
    tolerance : float, default=1e-5
    device : device, optional
    origin : {'native', 'center'}, default='center'

    Returns
    -------
    aff : (D+1, D+1) tensor
        Affine transformation matrix.
        The source affine matrix can be "corrected" by left-multiplying
        it with `aff`.
    vel : (D+1, D+1) tensor
        Initial velocity of the diffeomorphic transform.
        The full warp is `(aff @ aff_src).inv() @ aff_trg @ exp(vel)`
    moved : tensor
        Source image moved to target space.


    """
    # prepare all data tensors
    ((source, source_aff), (target, target_aff)) = prepare([source, target], device)
    backend = get_backend(source)
    dim = source.dim()

    # Rescale to [0, 1]
    source_min = source.min()
    source_max = source.max()
    target_min = target.min()
    target_max = target.max()
    source -= source_min
    source /= source_max - source_min
    target -= target_min
    target /= target_max - target_min

    # Shift origin
    if origin == 'center':
        shift = torch.as_tensor(target.shape, **backend)/2
        shift = -spatial.affine_matvec(target_aff, shift)
        target_aff[:-1, -1] += shift
        source_aff[:-1, -1] += shift

    # Prepare affine utils + Initialize parameters
    basis = spatial.affine_basis(group, dim, **backend)
    nb_prm = spatial.affine_basis_size(group, dim)
    if init is not None:
        parameters = torch.as_tensor(init, **backend)
        parameters = parameters.reshape(nb_prm)
    else:
        parameters = torch.zeros(nb_prm, **backend)
    parameters = Variable(parameters, requires_grad=True)
    velocity = torch.zeros([*target.shape, dim], **backend)
    velocity = Variable(velocity, requires_grad=True)

    def pull(q, vel):
        grid = spatial.exp(vel[None, ...])
        aff = core.linalg.expm(q, basis)
        aff = spatial.affine_matmul(aff, target_aff)
        aff = spatial.affine_lmdiv(source_aff, aff)
        grid = spatial.affine_matvec(aff, grid)
        moved = spatial.grid_pull(source[None, None, ...], grid,
                                  interpolation=interpolation, bound=bound,
                                  extrapolate=extrapolate)[0, 0]
        return moved

    # Prepare loss and optimizer
    if image_loss is None:
        image_loss_fn = nni.MutualInfoLoss()
        image_loss = lambda x, y: image_loss_fn(x[None, None, ...],
                                                y[None, None, ...])
    if vel_loss is None:
        vel_loss_fn = nni.MembraneLoss()
        vel_loss = lambda x: vel_loss_fn(core.utils.last2channel(x[None, ...]))

    optim = torch.optim.Adam([parameters, velocity], lr=1e-3)

    # Optim loop
    loss_val = core.constants.inf
    for n_iter in range(max_iter):

        loss_val0 = loss_val
        moved = pull(parameters, velocity)
        loss_val = image_loss(moved, target) + 0.1*vel_loss(velocity)
        loss_val.backward()
        optim.step()

        with torch.no_grad():
            crit = (loss_val0 - loss_val)
            if n_iter % 10 == 0:
                print('{:4d} {:12.6f} ({:12.6g})'
                      .format(n_iter, loss_val.item(), crit.item()),
                      end='\r')
            if crit.abs() < tolerance:
                break

    print('')
    with torch.no_grad():
        moved = pull(parameters, velocity)
        aff = core.linalg.expm(parameters, basis)
        if origin == 'center':
            aff[:-1, -1] -= shift
            shift = core.linalg.matvec(aff[:-1, :-1], shift)
            aff[:-1, -1] += shift
        aff = aff.inverse()
        aff.requires_grad_(False)
        return aff, velocity, moved
