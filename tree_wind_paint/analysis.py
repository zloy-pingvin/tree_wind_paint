# SPDX-License-Identifier: GPL-2.0-or-later
"""
Tree structure analysis for wind vertex colours.

Everything here works on plain numpy arrays read from a mesh in object mode:

- faces are split into bark and leaves by material (see resolve_roles);
- separate bark pieces are bridged to the piece they come closest to, so
  the bark becomes one connected graph rooted at the trunk base;
- geodesic distance from the trunk base runs over that graph (Dijkstra);
- a merge tree of that distance splits the bark into chains: vertices are
  taken from the farthest one down, every tip starts a chain, and where two
  chains meet the shorter one ends there and becomes a child of the longer
  one (tiny chains are bark bumps and get absorbed);
- the trunk chain is cut at the first fork whose side chain is about as long
  as the rest of the trunk, so a crown that splits into limbs gets one limb
  per chain instead of the longest limb counting as trunk;
- leaf cards (islands of leaf faces) hang on the nearest bark vertex.

Colour values are produced in display (sRGB) space, which is what the bytes
of a byte colour attribute hold and what FBX exports by default.
"""

import hashlib
import heapq
import math

import numpy as np
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

# BARE: bark of dead or leafless branches; part of the tree's structure, but
# no leaf hangs on it.
BARK, LEAF, SKIP, BARE = 0, 1, 2, 3
ROLE_IDS = {'BARK': BARK, 'LEAF': LEAF, 'SKIP': SKIP, 'BARE': BARE}
WOOD = (BARK, BARE)

LEAF_WORDS = ("leaf", "leaves", "foliage", "frond", "needle", "petal", "blossom",
              "flower", "лист", "хвоя", "иголк")
BARE_WORDS = ("dead", "dry", "bare", "сух", "мертв", "мёртв", "голы")
BARK_WORDS = ("bark", "trunk", "branch", "wood", "stem", "кора", "ствол", "ветк")

# Leaf cards are small loose islands; bark pieces are big. Face-weighted
# median island size of a material at or below this means leaves.
LEAF_ISLAND_MAX_VERTS = 64

UV_KEY_STEP = 1e-5

# Share of tree height above a trunk fork where more stems can leave.
FORK_ZONE = 0.1
# A crown splits into stems in the lower part of a tree; near the top of a
# conifer every upward branch is long next to the little trunk left, which
# is no fork.
FORK_MAX_HEIGHT = 0.6
# Share of tree height: bark pieces this close count as touching.
CONTACT_GAP = 0.015


class TreeError(Exception):
    pass


def _get(coll, attr, n, width, dtype):
    buf = np.empty(n * width, dtype=dtype)
    coll.foreach_get(attr, buf)
    return buf.reshape(n, width) if width > 1 else buf


class MeshData:
    """Plain arrays of a mesh (the mesh must not be in edit mode)."""

    def __init__(self, me):
        nv, nl, npoly = len(me.vertices), len(me.loops), len(me.polygons)
        self.nv, self.nl, self.npoly = nv, nl, npoly
        self.co = _get(me.vertices, "co", nv, 3, np.float32).astype(np.float64)
        self.loop_vert = _get(me.loops, "vertex_index", nl, 1, np.int32).astype(np.int64)
        self.poly_start = _get(me.polygons, "loop_start", npoly, 1, np.int32).astype(np.int64)
        self.poly_total = _get(me.polygons, "loop_total", npoly, 1, np.int32).astype(np.int64)
        self.poly_mat = _get(me.polygons, "material_index", npoly, 1, np.int32).astype(np.int64)
        self.poly_select = _get(me.polygons, "select", npoly, 1, bool)
        self.loop_poly = np.repeat(np.arange(npoly), self.poly_total)
        nxt = np.arange(nl) + 1
        if npoly:
            nxt[self.poly_start + self.poly_total - 1] = self.poly_start
        self.loop_next = nxt

    def checksum(self):
        h = hashlib.blake2b(digest_size=16)
        for a in (self.co, self.loop_vert, self.poly_start, self.poly_mat):
            h.update(np.ascontiguousarray(a).tobytes())
        return h.hexdigest()


def read_uv(me, name=None):
    """Per-corner UVs of the named (or active) UV map, or None."""
    layers = me.uv_layers
    layer = layers.get(name) if name else layers.active
    if layer is None:
        return None
    return _get(layer.data, "uv", len(me.loops), 2, np.float32).astype(np.float64)


def uv_keys(uv):
    """One int64 per corner; equal for corners at the same UV point."""
    q = np.round(uv / UV_KEY_STEP).astype(np.int64)
    return q[:, 0] * 4_000_000_007 + q[:, 1]


# --- graph helpers -----------------------------------------------------------

def components(n, a, b):
    """Connected components of a graph with n nodes and edges a[i]-b[i].

    Returns one label per node (the smallest node id of its component).
    """
    lab = np.arange(n)
    if len(a) == 0:
        return lab
    while True:
        m = np.minimum(lab[a], lab[b])
        new = lab.copy()
        np.minimum.at(new, a, m)
        np.minimum.at(new, b, m)
        while True:
            jumped = new[new]
            if np.array_equal(jumped, new):
                break
            new = jumped
        if np.array_equal(new, lab):
            return lab
        lab = new


def _csr(n, a, b, w=None):
    src = np.concatenate([a, b])
    dst = np.concatenate([b, a])
    order = np.argsort(src, kind="stable")
    ptr = np.zeros(n + 1, np.int64)
    ptr[1:] = np.cumsum(np.bincount(src, minlength=n))
    if w is None:
        return ptr, dst[order]
    return ptr, dst[order], np.concatenate([w, w])[order]


def _dijkstra(ptr, dst, w, sources, n, with_pred=False):
    dist = [math.inf] * n
    pred = [-1] * n
    ip, ds, ws = ptr.tolist(), dst.tolist(), w.tolist()
    heap = []
    for s in sources:
        dist[s] = 0.0
        heap.append((0.0, s))
    heapq.heapify(heap)
    while heap:
        dd, x = heapq.heappop(heap)
        if dd > dist[x]:
            continue
        for k in range(ip[x], ip[x + 1]):
            y = ds[k]
            nd = dd + ws[k]
            if nd < dist[y]:
                dist[y] = nd
                pred[y] = x
                heapq.heappush(heap, (nd, y))
    if with_pred:
        return np.array(dist), np.array(pred, np.int64)
    return np.array(dist)


def _kdtree(co, verts):
    kd = KDTree(len(verts))
    for v in verts.tolist():
        kd.insert(co[v], v)
    kd.balance()
    return kd


def _role_edges(md, face_role, roles):
    loops = np.where(np.isin(face_role[md.loop_poly], roles))[0]
    return md.loop_vert[loops], md.loop_vert[md.loop_next[loops]]


# --- material roles ----------------------------------------------------------

def guess_role_by_name(name):
    low = name.lower()
    if any(w in low for w in LEAF_WORDS):
        return LEAF
    if any(w in low for w in BARE_WORDS):
        return BARE
    if any(w in low for w in BARK_WORDS):
        return BARK
    return None


def resolve_roles(md, slot_roles, slot_names):
    """Role per material slot. slot_roles holds 'AUTO'/'BARK'/'BARE'/'LEAF'/'SKIP'.

    AUTO goes by the material name first, then by island size: leaf cards
    are small loose islands.
    """
    if not slot_roles:
        slot_roles, slot_names = ['AUTO'], [""]
    roles = []
    undecided = []
    for i, (role, name) in enumerate(zip(slot_roles, slot_names)):
        if role != 'AUTO':
            roles.append(ROLE_IDS[role])
            continue
        guess = guess_role_by_name(name)
        roles.append(guess)
        if guess is None:
            undecided.append(i)
    if undecided:
        lab = components(md.nv, md.loop_vert, md.loop_vert[md.loop_next])
        size = np.bincount(lab, minlength=md.nv)
        first_vert = md.loop_vert[md.poly_start]
        poly_mat = np.clip(md.poly_mat, 0, len(roles) - 1)
        for i in undecided:
            faces = np.where(poly_mat == i)[0]
            if not len(faces):
                roles[i] = SKIP
                continue
            median = np.median(size[lab[first_vert[faces]]])
            roles[i] = LEAF if median <= LEAF_ISLAND_MAX_VERTS else BARK
    return roles


def face_roles(md, roles):
    return np.asarray(roles, np.int64)[np.clip(md.poly_mat, 0, len(roles) - 1)]


# --- structure ---------------------------------------------------------------

class Tree:
    """Result of analyze(); per-vertex arrays have one entry per mesh vertex."""
    d = None          # geodesic distance from the trunk base (bark), nan elsewhere
    chain = None      # chain id per bark vertex, -1 elsewhere
    tip_d = None      # per chain
    base_d = None     # per chain: distance where it starts (attaches)
    parent = None     # per chain, -1 for the trunk
    grow_on = None    # per chain: the chain it physically grows from (differs from
                      # parent only for crown stems made limbs, see _split_trunk)
    tip_vert = None   # per chain: its farthest vertex
    level = None      # per chain: 0 trunk, 1 limbs on the trunk, ...
    root = 0          # trunk chain id
    axis = None       # xy of the trunk base
    height = 1.0
    leaf_island = None   # per vertex, -1 for non-leaf vertices
    leaf_base = None     # per leaf island: vertex nearest to the bark
    leaf_host = None     # per leaf island: bark vertex it hangs on
    leaf_near = None     # per vertex: nearest bark vertex of a leaf vertex, -1 elsewhere
    bare = None          # per vertex: bark of the BARE role only (dead branches)
    graph = None         # (a, b): bark edges plus bridges
    bridges = 0
    bridge_pairs = None  # (n, 2): parent-side vertex, entry vertex of a loose bark piece
    island = None        # per vertex: bark island id, -1 elsewhere


def _surface_contacts(md, face_role, bark, island, max_gap):
    """Every bark vertex that comes within max_gap of the bark SURFACE of
    another island, as links (u, x, weight) to each corner x of the face it
    comes nearest to, weighted by the gap plus the way along that face.
    A low-poly trunk has its vertices a metre apart, so a branch touching it
    between two rings is far from any trunk vertex."""
    faces = np.where(np.isin(face_role, WOOD))[0]
    co = md.co
    starts = md.poly_start[faces].tolist()
    totals = md.poly_total[faces].tolist()
    polys = [md.loop_vert[s:s + t].tolist() for s, t in zip(starts, totals)]
    bvh = BVHTree.FromPolygons(co.tolist(), polys, all_triangles=False)
    face_isl = island[md.loop_vert[md.poly_start[faces]]].tolist()
    isl = island.tolist()
    links = []
    for u in bark.tolist():
        iu = isl[u]
        best = None
        for loc, _nrm, idx, dist in bvh.find_nearest_range(co[u], max_gap):
            if face_isl[idx] != iu and (best is None or dist < best[0]):
                best = (dist, idx, loc)
        if best is None:
            continue
        dist, idx, loc = best
        hit = np.array(loc)
        for x in polys[idx]:
            links.append((u, x, dist + float(np.linalg.norm(hit - co[x]))))
    return links


def _bridge_islands(co, bark, island, root_isl):
    """Links that join every bark island to the root island: [(u, v, gap)]."""
    n_isl = int(island[bark].max()) + 1
    if n_isl == 1:
        return []
    kd = _kdtree(co, bark)
    isl = island.tolist()
    best = {}
    for u in bark.tolist():
        iu = isl[u]
        for _co, v, dist in kd.find_n(co[u], 12):
            iv = isl[v]
            if iv != iu:
                key = (iu, iv)
                if key not in best or dist < best[key][0]:
                    best[key] = (dist, u, v)
                break
    links = [[] for _ in range(n_isl)]
    for (iu, iv), (dist, u, v) in best.items():
        links[iu].append((dist, iv, u, v))
        links[iv].append((dist, iu, v, u))

    members = [[] for _ in range(n_isl)]
    for v in bark.tolist():
        members[isl[v]].append(v)

    reached = [False] * n_isl
    bridges = []

    def grow(start):
        reached[start] = True
        heap = list(links[start])
        heapq.heapify(heap)
        while heap:
            dist, iv, u, v = heapq.heappop(heap)
            if reached[iv]:
                continue
            reached[iv] = True
            bridges.append((u, v, dist))
            for item in links[iv]:
                if not reached[item[1]]:
                    heapq.heappush(heap, item)

    grow(root_isl)
    while not all(reached):
        # A group of islands that only touch each other: link its closest
        # vertex to the reached part, then keep growing from there.
        reached_isl = set(i for i in range(n_isl) if reached[i])
        best_link = None
        for i in range(n_isl):
            if reached[i]:
                continue
            step = max(1, len(members[i]) // 64)
            for u in members[i][::step]:
                found = kd.find(co[u], filter=lambda x: isl[x] in reached_isl)
                if found[1] is not None and (best_link is None or found[2] < best_link[0]):
                    best_link = (found[2], i, found[1], u)
        dist, i, v, u = best_link
        bridges.append((v, u, dist))
        grow(i)
    return bridges


def analyze(md, face_role, fork_ratio=0.5, min_branch=0.01, fork_angle=math.radians(40.0)):
    """Build the Tree for a mesh. min_branch is a fraction of tree height,
    fork_angle in radians."""
    tree = Tree()
    co = md.co
    nv = md.nv

    ba, bb = _role_edges(md, face_role, WOOD)
    bark_mask = np.zeros(nv, bool)
    bark_mask[ba] = True
    bark_mask[bb] = True
    bark = np.where(bark_mask)[0]
    if not len(bark):
        raise TreeError("No bark faces: set the bark material role")

    lab = components(nv, ba, bb)
    island = np.full(nv, -1, np.int64)
    island[bark] = np.unique(lab[bark], return_inverse=True)[1].ravel()
    tree.island = island

    zs = co[bark, 2]
    zmin = float(zs.min())
    height = max(float(zs.max()) - zmin, 1e-6)
    root_v = int(bark[np.argmin(zs)])
    root_isl = island[root_v]
    in_root = bark[island[bark] == root_isl]
    sources = in_root[co[in_root, 2] <= zmin + 0.01 * height]
    tree.axis = co[sources, :2].mean(axis=0)
    tree.height = height

    bridges = _bridge_islands(co, bark, island, root_isl)
    if bridges:
        contacts = _surface_contacts(md, face_role, bark, island, CONTACT_GAP * height)
        # A piece of bark attaches where it is nearest to the root along the
        # tree, not where its gap is smallest: in a dense crown a piece can
        # touch a neighbour with its tip, and then its gradient would run
        # backwards. Walk over every contact, then keep, per island, the
        # contact the shortest path came in through.
        links = bridges + contacts
        lu = np.array([l[0] for l in links], np.int64)
        lv = np.array([l[1] for l in links], np.int64)
        lw = np.array([max(l[2], 1e-6) for l in links])
        ptr, dst, w = _csr(nv, np.concatenate([ba, lu]), np.concatenate([bb, lv]),
                           np.concatenate([np.linalg.norm(co[ba] - co[bb], axis=1), lw]))
        d_all, pred = _dijkstra(ptr, dst, w, sources.tolist(), nv, with_pred=True)
        order = bark[np.lexsort((d_all[bark], island[bark]))]
        first = np.ones(len(order), bool)
        first[1:] = island[order][1:] != island[order][:-1]
        weight = {}
        for u, v, wt in links:
            for key in ((u, v), (v, u)):
                if wt < weight.get(key, math.inf):
                    weight[key] = wt
        bridges = []
        for m in order[first].tolist():
            u = int(pred[m])
            if island[m] != root_isl and u >= 0 and island[u] != island[m]:
                bridges.append((u, m, weight[(u, m)]))
    tree.bridges = len(bridges)
    tree.bridge_pairs = np.array([(b[0], b[1]) for b in bridges], np.int64).reshape(-1, 2)
    if bridges:
        bu = np.array([b[0] for b in bridges], np.int64)
        bv = np.array([b[1] for b in bridges], np.int64)
        bw = np.array([max(b[2], 1e-6) for b in bridges])
        ga, gb = np.concatenate([ba, bu]), np.concatenate([bb, bv])
        gw = np.concatenate([np.linalg.norm(co[ba] - co[bb], axis=1), bw])
    else:
        ga, gb = ba, bb
        gw = np.linalg.norm(co[ba] - co[bb], axis=1)
    tree.graph = (ga, gb)  # bark edges and bridges
    ptr, dst, w = _csr(nv, ga, gb, gw)
    d = _dijkstra(ptr, dst, w, sources.tolist(), nv)
    d[~bark_mask] = np.nan
    tree.d = d

    _merge_tree(tree, bark, ptr, dst, min_branch * height)
    _split_trunk(tree, co, fork_ratio, fork_angle)
    _levels(tree)
    # leaves never hang on bare (dead) bark, unless there is nothing else
    la, lb = _role_edges(md, face_role, (BARK,))
    live = np.zeros(nv, bool)
    live[la] = True
    live[lb] = True
    tree.bare = bark_mask & ~live
    _hang_leaves(tree, md, face_role, bark[live[bark]] if live[bark].any() else bark)
    return tree


def _merge_tree(tree, bark, ptr, dst, min_len):
    d = tree.d
    dl = d.tolist()
    ip, ds = ptr.tolist(), dst.tolist()
    order = bark[np.argsort(-d[bark], kind="stable")].tolist()

    uf = list(range(len(dl)))

    def find(x):
        while uf[x] != x:
            uf[x] = uf[uf[x]]
            x = uf[x]
        return x

    added = [False] * len(dl)
    chain = [-1] * len(dl)
    tip_d, base_d, parent, tip_vert, alive = [], [], [], [], []
    # comp root -> [max d, current chain, members or None, chains]
    # members are kept only while the comp is short enough to be absorbed.
    comp = {}

    for v in order:
        dv = dl[v]
        roots = []
        for k in range(ip[v], ip[v + 1]):
            u = ds[k]
            if added[u]:
                r = find(u)
                if r not in roots:
                    roots.append(r)
        added[v] = True
        if not roots:
            c = len(tip_d)
            tip_d.append(dv)
            base_d.append(dv)
            parent.append(-1)
            tip_vert.append(v)
            alive.append(True)
            comp[v] = [dv, c, [v], [c]]
            chain[v] = c
            continue
        roots.sort(key=lambda r: -comp[r][0])
        elder = comp[roots[0]]
        for r in roots[1:]:
            young = comp.pop(r)
            if young[0] - dv < min_len and young[2] is not None:
                for m in young[2]:
                    chain[m] = elder[1]
                for c in young[3]:
                    alive[c] = False
            else:
                parent[young[1]] = elder[1]
                base_d[young[1]] = dv
                elder[3].extend(young[3])
            if elder[2] is not None:
                if young[2] is None:
                    elder[2] = None
                else:
                    elder[2].extend(young[2])
            uf[r] = roots[0]
        uf[v] = roots[0]
        chain[v] = elder[1]
        if elder[2] is not None:
            elder[2].append(v)
            if elder[0] - dv >= min_len:
                elder[2] = None

    # Remaining comps: normally one (the bridges connect all bark).
    roots_left = [c[1] for c in comp.values()]
    chain = np.array(chain, np.int64)
    alive_ids = np.where(np.array(alive))[0]
    remap = np.full(len(alive), -1, np.int64)
    remap[alive_ids] = np.arange(len(alive_ids))
    chain[chain >= 0] = remap[chain[chain >= 0]]
    tree.chain = chain
    tree.tip_d = np.array(tip_d)[alive_ids]
    tree.base_d = np.array(base_d)[alive_ids]
    par = np.array(parent, np.int64)[alive_ids]
    par[par >= 0] = remap[par[par >= 0]]
    tree.parent = par
    tree.tip_vert = np.array(tip_vert, np.int64)[alive_ids]
    roots_left = [int(remap[c]) for c in roots_left]
    for c in roots_left:
        tree.base_d[c] = float(np.nanmin(d[chain == c]))
    # the trunk is the remaining chain that holds the distance origin
    tree.root = min(roots_left, key=lambda c: tree.base_d[c])


def _split_trunk(tree, co, fork_ratio, fork_angle):
    """End the trunk at the first fork whose side chain is about as long as
    the rest of the trunk and grows upward like a second stem (within
    fork_angle of vertical); the trunk's continuation becomes a limb.
    A long side branch that goes sideways (a conifer's) is not a fork."""
    root = tree.root
    tree.grow_on = tree.parent.copy()
    kids = np.where(tree.parent == root)[0]
    if not len(kids) or fork_ratio <= 0:
        return
    top = tree.tip_d[root]
    cos_max = math.cos(fork_angle)
    bark_z = co[tree.chain >= 0, 2]
    z_limit = bark_z.min() + FORK_MAX_HEIGHT * tree.height

    def stem(c):
        """Long as the rest of the trunk and growing upward: a second stem."""
        if tree.tip_d[c] - tree.base_d[c] < fork_ratio * (top - tree.base_d[c]):
            return False
        vs = np.where(tree.chain == c)[0]
        base = co[vs[np.argmin(tree.d[vs])]]
        if base[2] > z_limit:
            return False
        way = co[tree.tip_vert[c]] - base
        return way[2] >= cos_max * np.linalg.norm(way)

    fork = next((tree.base_d[c] for c in kids[np.argsort(tree.base_d[kids])] if stem(c)), None)
    if fork is None:
        return
    limb = len(tree.tip_d)
    tree.tip_d = np.append(tree.tip_d, top)
    tree.base_d = np.append(tree.base_d, fork)
    tree.parent = np.append(tree.parent, root)
    tree.grow_on = np.append(tree.grow_on, root)
    tree.tip_vert = np.append(tree.tip_vert, tree.tip_vert[root])
    upper = (tree.chain == root) & (tree.d > fork)
    tree.chain[upper] = limb
    moved = (tree.parent == root) & (tree.base_d > fork)
    moved[limb] = False
    tree.parent[moved] = limb
    tree.grow_on[moved] = limb
    tree.tip_d[root] = fork
    lower = np.where(tree.chain == root)[0]
    tree.tip_vert[root] = lower[np.argmax(tree.d[lower])]
    # A crown often splits into several stems a little apart: stems that
    # leave the trunk's continuation just above the fork are limbs of
    # their own. They still grow on that continuation (grow_on), which
    # their blue starts from.
    zone = FORK_ZONE * tree.height
    for c in np.where((tree.parent == limb) & (tree.base_d <= fork + zone))[0]:
        if stem(c):
            tree.parent[c] = root


def _levels(tree):
    n = len(tree.tip_d)
    level = np.full(n, -1, np.int64)
    level[tree.root] = 0
    for c in range(n):
        path = []
        x = c
        while level[x] < 0 and tree.parent[x] >= 0:
            path.append(x)
            x = tree.parent[x]
        base = level[x] if level[x] >= 0 else 0
        for i, y in enumerate(reversed(path)):
            level[y] = base + i + 1
        if level[c] < 0:
            level[c] = 0
    tree.level = level


def _hang_leaves(tree, md, face_role, bark):
    la, lb = _role_edges(md, face_role, (LEAF,))
    nv = md.nv
    leaf_mask = np.zeros(nv, bool)
    leaf_mask[la] = True
    leaf_mask[lb] = True
    leaves = np.where(leaf_mask)[0]
    tree.leaf_island = np.full(nv, -1, np.int64)
    tree.leaf_near = np.full(nv, -1, np.int64)
    if not len(leaves):
        tree.leaf_base = np.zeros(0, np.int64)
        tree.leaf_host = np.zeros(0, np.int64)
        return
    lab = components(nv, la, lb)
    isl = np.unique(lab[leaves], return_inverse=True)[1].ravel()
    tree.leaf_island[leaves] = isl
    kd = _kdtree(md.co, bark)
    near_v = np.empty(len(leaves), np.int64)
    near_d = np.empty(len(leaves))
    co = md.co
    for i, v in enumerate(leaves.tolist()):
        _c, idx, dist = kd.find(co[v])
        near_v[i] = idx
        near_d[i] = dist
    order = np.lexsort((near_d, isl))
    first = np.ones(len(order), bool)
    first[1:] = isl[order][1:] != isl[order][:-1]
    picks = order[first]
    tree.leaf_base = leaves[picks]
    tree.leaf_host = near_v[picks]
    tree.leaf_near[leaves] = near_v


# --- colours -----------------------------------------------------------------

class PaintParams:
    # The engine sways the trunk itself (by height, as in Crysis), so the
    # trunk stays at B = 0. B grows with distance along a limb (a branch on
    # the trunk) and everything growing on it reads the same function, so
    # the colour where a branch or a leaf attaches is exactly its parent's,
    # for any curve. G is one value per limb: what one gradient of B runs
    # along is one branch.
    bend_power = 2.0       # steepness of B: 1 is linear
    rigid_leafless = True  # branches carrying no leaves keep the B of their attachment
    group_seed = 0
    flutter_power = 3.0    # steepness of R from leaf stem to tip
    # fixed, not shown to the user
    bend_min_length = 0.15  # share of height: a gradient is never squeezed into less
    leaf_ramp = 0.5        # 0: a leaf takes its host's B; 1: B keeps growing along the leaf
    group_low = 0.05       # limb G values are spread over [low, high]
    group_high = 0.8       # (kept below trunk_g so no limb looks like the trunk)
    trunk_g = 1.0
    flutter_by_uv = True   # one stem per leaf card type, same R for corners at one UV point
    bark_flutter = 0.0


def _limbs(tree):
    """Per chain: its ancestor on level 1 (the trunk for the trunk)."""
    limb = np.arange(len(tree.tip_d))
    for c in range(len(limb)):
        x = c
        while tree.level[x] > 1:
            x = tree.parent[x]
        limb[c] = x
    return limb


def _leafy(tree):
    """Per chain: whether leaves hang on it or on anything growing on it."""
    sub = np.zeros(len(tree.tip_d), bool)
    if len(tree.leaf_host):
        sub[tree.chain[tree.leaf_host]] = True
    for c in np.argsort(-tree.level, kind="stable"):
        par = tree.parent[c]
        if par >= 0 and sub[c]:
            sub[par] = True
    return sub


def _subtree_tip(tree, use=None):
    """Per chain: the farthest tip of the chain and everything growing on it
    (only chains where use is True count, the chain's own tip otherwise)."""
    sub = tree.tip_d.copy() if use is None else np.where(use, tree.tip_d, -np.inf)
    for c in np.argsort(-tree.level, kind="stable"):
        par = tree.parent[c]
        if par >= 0 and sub[c] > sub[par]:
            sub[par] = sub[c]
    return np.where(np.isfinite(sub), sub, tree.tip_d)


class _Bend:
    """B as a function of (chain, distance from the trunk base)."""

    def __init__(self, tree, p):
        self.tree = tree
        self.power = p.bend_power
        root = tree.root
        n = len(tree.tip_d)
        min_len = max(p.bend_min_length * tree.height, 1e-6)
        # A leafless branch (and all it carries) is held at the B of the
        # point where the first leafless branch on its way attaches.
        leafy = _leafy(tree)
        self.held_at = np.full(n, -1, np.int64)
        if p.rigid_leafless and leafy.any():
            for c in np.lexsort((tree.level, tree.base_d)):
                par = tree.grow_on[c]
                if par < 0:
                    continue
                if self.held_at[par] >= 0:
                    self.held_at[c] = self.held_at[par]
                elif not leafy[c]:
                    self.held_at[c] = c
        limb = _limbs(tree)
        sub = _subtree_tip(tree, leafy if (self.held_at >= 0).any() else None)
        self.base = tree.base_d[limb]
        self.span = np.maximum(sub[limb] - tree.base_d[limb], min_len)
        self.start = np.zeros(n)
        # crown stems made limbs start from the limb they grow on
        for c in np.argsort(tree.base_d, kind="stable"):
            on = tree.grow_on[c]
            if limb[c] == c and on >= 0 and on != root:
                self.start[limb == c] = self(np.array([on]), np.array([tree.base_d[c]]))[0]

    def __call__(self, c, d):
        held = self.held_at[c]
        on_hold = held >= 0
        c = np.where(on_hold, held, c)
        d = np.where(on_hold, self.tree.base_d[np.maximum(held, 0)], d)
        t = np.clip((d - self.base[c]) / self.span[c], 0.0, 1.0) ** self.power
        b = self.start[c] + (1.0 - self.start[c]) * t
        return np.where(c == self.tree.root, 0.0, b)


def _phases(tree, p):
    """G per chain: one value per limb and everything it carries."""
    n = len(tree.tip_d)
    unit = _limbs(tree)
    heads = sorted(set(unit.tolist()) - {tree.root})
    # neighbours around the trunk get far-apart values
    co_tip = tree.co_tip
    ang = {h: math.atan2(co_tip[h][1] - tree.axis[1], co_tip[h][0] - tree.axis[0]) for h in heads}
    heads.sort(key=lambda h: ang[h])
    golden = 0.6180339887498949
    off = (p.group_seed * 0.2718281828) % 1.0
    value = {tree.root: p.trunk_g}
    for i, h in enumerate(heads):
        value[h] = p.group_low + (p.group_high - p.group_low) * ((off + i * golden) % 1.0)
    return np.array([value[unit[c]] for c in range(n)])


def _stems_by_uv(tree, md, face_role, uv, stems):
    """One stem point per leaf card type: the UV point most copies of the card
    have nearest to the bark. Copies that have it use it as their stem."""
    lv = md.loop_vert
    loops = np.where(face_role[md.loop_poly] == LEAF)[0]
    keys = uv_keys(uv[loops])
    vkey = np.zeros(md.nv, np.int64)
    vkey[lv[loops]] = keys
    # card types: faces linked through the UV points they share
    ukeys, kinv = np.unique(keys, return_inverse=True)
    lab = components(md.npoly + len(ukeys), md.loop_poly[loops], md.npoly + kinv.ravel())
    n_isl = len(stems)
    card = np.full(n_isl, -1, np.int64)
    card[tree.leaf_island[lv[loops]]] = lab[md.loop_poly[loops]]
    # votes: (card, uv key of its current stem)
    pairs, counts = np.unique(np.stack([card, vkey[stems]], axis=1), axis=0, return_counts=True)
    order = np.lexsort((-counts, pairs[:, 0]))
    pairs = pairs[order]
    first = np.ones(len(pairs), bool)
    first[1:] = pairs[1:, 0] != pairs[:-1, 0]
    win_card, win_key = pairs[first, 0], pairs[first, 1]
    leaves = np.where(tree.leaf_island >= 0)[0]
    isl = tree.leaf_island[leaves]
    pos = np.searchsorted(win_card, card[isl])
    hit = vkey[leaves] == win_key[np.clip(pos, 0, len(win_key) - 1)]
    out = stems.copy()
    out[isl[hit]] = leaves[hit]
    return out


def compute_colors(tree, md, face_role, p, uv=None):
    """Per-corner RGB in sRGB space and the mask of corners it covers."""
    co = md.co
    nv = md.nv
    tree.co_tip = co[tree.tip_vert]
    bend = _Bend(tree, p)
    gval = _phases(tree, p)

    vR = np.zeros(nv)
    vG = np.zeros(nv)
    vB = np.zeros(nv)
    bark = np.where(tree.chain >= 0)[0]
    c = tree.chain[bark]
    vB[bark] = bend(c, tree.d[bark])
    vG[bark] = gval[c]
    if p.rigid_leafless and tree.bare.any():
        # A connected piece of dead bark (a dry tip, a stub, dead twigs on
        # it, joined by welds or bridges) holds one blue: the one of the
        # point where the dead part begins.
        ga, gb = tree.graph
        keep = tree.bare[ga] & tree.bare[gb]
        lab = components(nv, ga[keep], gb[keep])
        dead = np.where(tree.bare)[0]
        order = np.lexsort((tree.d[dead], lab[dead]))
        first = np.ones(len(order), bool)
        first[1:] = lab[dead][order][1:] != lab[dead][order][:-1]
        heads = dead[order[first]]
        head_of = np.full(nv, -1, np.int64)
        head_of[lab[heads]] = heads
        h = head_of[lab[dead]]
        vB[dead] = bend(tree.chain[h], tree.d[h])
    vR[bark] = p.bark_flutter

    lR = np.zeros(nv)
    lG = np.zeros(nv)
    lB = np.zeros(nv)
    leaves = np.where(tree.leaf_island >= 0)[0]
    stems = tree.leaf_base
    if len(leaves):
        if p.flutter_by_uv and uv is not None:
            stems = _stems_by_uv(tree, md, face_role, uv, stems)
        isl = tree.leaf_island[leaves]
        stem = stems[isl]
        host = tree.leaf_near[stem]
        hc = tree.chain[host]
        dh = tree.d[host]
        dist = np.linalg.norm(co[leaves] - co[stem], axis=1)
        # at the stem both equal the bark vertex the leaf hangs on
        lB[leaves] = bend(hc, dh + p.leaf_ramp * dist)
        lG[leaves] = gval[hc]
        rmax = np.zeros(len(stems))
        np.maximum.at(rmax, isl, dist)
        lR[leaves] = (dist / np.maximum(rmax[isl], 1e-9)) ** p.flutter_power

    loop_role = face_role[md.loop_poly]
    lv = md.loop_vert
    rgb = np.zeros((md.nl, 3))
    is_bark = np.isin(loop_role, WOOD)
    is_leaf = loop_role == LEAF
    rgb[is_bark] = np.stack([vR[lv[is_bark]], vG[lv[is_bark]], vB[lv[is_bark]]], axis=1)
    rgb[is_leaf] = np.stack([lR[lv[is_leaf]], lG[lv[is_leaf]], lB[lv[is_leaf]]], axis=1)

    if p.flutter_by_uv and uv is not None and is_leaf.any():
        idx = np.where(is_leaf)[0]
        _u, inv = np.unique(uv_keys(uv[idx]), return_inverse=True)
        inv = inv.ravel()
        mean = np.bincount(inv, weights=rgb[idx, 0]) / np.bincount(inv)
        rgb[idx, 0] = mean[inv]
    if len(leaves):
        # the stem never flutters: it must stay on the branch
        rgb[is_leaf & np.isin(lv, stems), 0] = 0.0

    return np.clip(rgb, 0.0, 1.0), loop_role != SKIP


def summary(tree):
    return {
        "chains": len(tree.tip_d),
        "limbs": int((tree.level == 1).sum()),
        "levels": int(tree.level.max()) if len(tree.level) else 0,
        "leaves": len(tree.leaf_base),
        "bridges": tree.bridges,
    }
