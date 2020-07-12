import math
import heapq
import time
import numpy as np
import matplotlib.pyplot as plt
import scipy.spatial.kdtree as kd

import astar
import reeds_shepp_path as rs


class C:  # Parameter config
    PI = math.pi

    XY_RESO = 2.0  # [m]
    YAW_RESO = np.deg2rad(10.0)  # [rad]
    GOAL_YAW_ERROR = np.deg2rad(5.0)  # [rad]
    MOVE_STEP = 0.1  # [m] path interporate resolution
    N_STEER = 20.0  # steer command number
    COLLISION_CHECK_STEP = 8  # skip number for collision check
    EXTEND_BOUND = 1

    GEAR_COST = 20.0  # switch back penalty cost
    BACKWARD_COST = 5.0  # backward penalty cost
    STEER_CHANGE_COST = 5.0  # steer angle change penalty cost
    STEER_ANGLE_COST = 1.0  # steer angle penalty cost
    H_COST = 5.0  # Heuristic cost penalty cost

    LF = 4.5  # [m] distance from rear to vehicle front end of vehicle
    LB = 1.0  # [m] distance from rear to vehicle back end of vehicle
    W = 2.6  # [m] width of vehicle
    WB = 3.7  # [m] Wheel base
    TR = 0.5  # Tyre radius [m] for plot
    TW = 1.0  # Tyre width [m] for plot
    MAX_STEER = 0.6  # [rad] maximum steering angle


class Node:
    def __init__(self, xind, yind, yawind, direction, x, y,
                 yaw, directions, steer, cost, pind):
        self.xind = xind
        self.yind = yind
        self.yawind = yawind
        self.direction = direction
        self.x = x
        self.y = y
        self.yaw = yaw
        self.directions = directions
        self.steer = steer
        self.cost = cost
        self.pind = pind


class Para:
    def __init__(self, minx, miny, minyaw, maxx, maxy, maxyaw,
                 xw, yw, yaww, xyreso, yawreso, ox, oy, kdtree):
        self.minx = minx
        self.miny = miny
        self.minyaw = minyaw
        self.maxx = maxx
        self.maxy = maxy
        self.maxyaw = maxyaw
        self.xw = xw
        self.yw = yw
        self.yaww = yaww
        self.xyreso = xyreso
        self.yawreso = yawreso
        self.ox = ox
        self.oy = oy
        self.kdtree = kdtree


class Path:
    def __init__(self, x, y, yaw, direction, cost):
        self.x = x
        self.y = y
        self.yaw = yaw
        self.direction = direction
        self.cost = cost


class QueuePrior:
    """
    Class: QueuePrior
    Description: QueuePrior reorders elements using value [priority]
    """

    def __init__(self):
        self.queue = []

    def empty(self):
        return len(self.queue) == 0

    def put(self, item, priority):
        heapq.heappush(self.queue, (priority, item))  # reorder x using priority

    def get(self):
        return heapq.heappop(self.queue)[1]  # pop out the smallest item


def hybrid_astar_planning(sx, sy, syaw, gx, gy, gyaw, ox, oy, xyreso, yawreso):
    sxr, syr = round(sx / xyreso), round(sy / xyreso)
    gxr, gyr = round(gx / xyreso), round(gy / xyreso)
    syawr, gyawr = round(syaw / yawreso), round(gyaw / yawreso)

    nstart = Node(sxr, syr, syawr, 1, [sx], [sy], [syaw], [1], 0.0, 0.0, -1)
    ngoal = Node(gxr, gyr, gyawr, 1, [gx], [gy], [gyaw], [1], 0.0, 0.0, -1)

    kdtree = kd.KDTree([[x, y] for x, y in zip(ox, oy)])
    P = calc_parameters(ox, oy, xyreso, yawreso, kdtree)

    hmap = astar.calc_holonomic_heuristic_with_obstacle(ngoal, P.ox, P.oy, P.xyreso, 1.0)
    steer, direc = calc_motion_set()

    fnode = None

    open_set, closed_set = {calc_index(nstart, P): nstart}, {}

    qp = QueuePrior()
    qp.put(calc_index(nstart, P), calc_hybrid_cost(nstart, hmap, P))

    while True:
        if not open_set:
            return

        ind = qp.get()
        n_curr = open_set[ind]
        closed_set[ind] = n_curr
        open_set.pop(ind)

        update, fpath = update_node_with_analystic_expantion(n_curr, ngoal, gyaw, P)

        if update:
            fnode = fpath
            break

        for i in range(len(steer)):
            node = calc_next_node(n_curr, ind, steer[i], direc[i], P)

            if not node:
                continue

            node_ind = calc_index(node, P)

            if node_ind in closed_set:
                continue

            if node_ind not in open_set:
                open_set[node_ind] = node
                qp.put(node_ind, calc_hybrid_cost(node, hmap, P))
            else:
                if open_set[node_ind].cost > node.cost:
                    open_set[node_ind] = node

    return extract_path(closed_set, fnode, nstart)


def extract_path(closed, ngoal, nstart):
    rx = list(reversed(ngoal.x))
    ry = list(reversed(ngoal.y))
    ryaw = list(reversed(ngoal.yaw))
    direction = list(reversed(ngoal.directions))
    nid = ngoal.pind
    finalcost = ngoal.cost

    while True:
        n = closed[nid]
        rx = rx + list(reversed(n.x))
        ry = ry + list(reversed(n.y))
        ryaw = ryaw + list(reversed(n.yaw))
        direction = direction + list(reversed(n.directions))
        nid = n.pind

        if is_same_grid(n, nstart):
            break

    rx = list(reversed(rx))
    ry = list(reversed(ry))
    ryaw = list(reversed(ryaw))
    direction = list(reversed(direction))

    direction[0] = direction[1]
    path = Path(rx, ry, ryaw, direction, finalcost)

    return path


def calc_next_node(n_curr, c_id, u, d, P):
    step = C.XY_RESO * 2

    nlist = math.ceil(step / C.MOVE_STEP)
    xlist = [n_curr.x[-1] + d * C.MOVE_STEP * math.cos(n_curr.yaw[-1])]
    ylist = [n_curr.y[-1] + d * C.MOVE_STEP * math.sin(n_curr.yaw[-1])]
    yawlist = [rs.pi_2_pi(n_curr.yaw[-1] + d * C.MOVE_STEP / C.WB * math.tan(u))]

    for i in range(nlist - 1):
        xlist.append(xlist[-1] + d * C.MOVE_STEP * math.cos(yawlist[-1]))
        ylist.append(ylist[-1] + d * C.MOVE_STEP * math.sin(yawlist[-1]))
        yawlist.append(rs.pi_2_pi(yawlist[-1] + d * C.MOVE_STEP / C.WB * math.tan(u)))

    xind = round(xlist[-1] / P.xyreso)
    yind = round(ylist[-1] / P.xyreso)
    yawind = round(yawlist[-1] / P.yawreso)

    if not check_index(xind, yind, xlist, ylist, yawlist, P):
        return None

    cost = 0.0

    if d > 0:
        direction = True
        cost += abs(step)
    else:
        direction = False
        cost += abs(step) * C.BACKWARD_COST

    if direction != n_curr.direction:  # switch back penalty
        cost += C.GEAR_COST

    cost += C.STEER_ANGLE_COST * abs(u)  # steer angle penalyty
    cost += C.STEER_CHANGE_COST * abs(n_curr.steer - u)  # steer change penalty
    cost = n_curr.cost + cost

    directions = [direction for _ in range(len(xlist))]

    node = Node(xind, yind, yawind, direction, xlist, ylist,
                yawlist, directions, u, cost, c_id)

    return node


def check_index(xind, yind, xlist, ylist, yawlist, P):
    if xind <= P.minx or \
            xind >= P.maxx or \
            yind <= P.miny or \
            yind >= P.maxy:
        return False

    ind = range(0, len(xlist), C.COLLISION_CHECK_STEP)

    nodex = [xlist[k] for k in ind]
    nodey = [ylist[k] for k in ind]
    nodeyaw = [yawlist[k] for k in ind]

    if not check_collision(nodex, nodey, nodeyaw, P):
        return False

    return True


def update_node_with_analystic_expantion(n_curr, ngoal, gyaw, P):
    path = analystic_expantion(n_curr, ngoal, P)  # rs path: n_curr -> ngoal

    if not path:
        return False, None

    fx = path.x[1:-1]
    fy = path.y[1:-1]
    fyaw = path.yaw[1:-1]
    fd = path.directions[1:-1]

    fcost = n_curr.cost + calc_rs_path_cost(path)
    fpind = calc_index(n_curr, P)
    fsteer = 0.0

    fpath = Node(n_curr.xind, n_curr.yind, n_curr.yawind, n_curr.direction,
                 fx, fy, fyaw, fd, fsteer, fcost, fpind)

    return True, fpath


def analystic_expantion(node, ngoal, P):
    sx, sy, syaw = node.x[-1], node.y[-1], node.yaw[-1]
    gx, gy, gyaw = ngoal.x[-1], ngoal.y[-1], ngoal.yaw[-1]

    maxc = math.tan(C.MAX_STEER) / C.WB
    paths = rs.calc_all_paths(sx, sy, syaw, gx, gy, gyaw, maxc, step_size=C.MOVE_STEP)

    if not paths:
        return None

    paths_collision_free = []
    for path in paths:
        ind = range(0, len(path.x), C.COLLISION_CHECK_STEP)

        pathx = [path.x[k] for k in ind]
        pathy = [path.y[k] for k in ind]
        pathyaw = [path.yaw[k] for k in ind]

        if check_collision(pathx, pathy, pathyaw, P):
            paths_collision_free.append(path)

    if not paths_collision_free:
        return None

    pathcost = []
    for path in paths_collision_free:
        pathcost.append(calc_rs_path_cost(path))

    return paths_collision_free[pathcost.index(min(pathcost))]


def check_collision(x, y, yaw, P):

    for ix, iy, iyaw in zip(x, y, yaw):
        ids = P.kdtree.query_ball_point([ix, iy], C.LF * 2)

        if not ids:
            continue

        for i in ids:
            xo = P.ox[i] - ix
            yo = P.oy[i] - iy
            theta = iyaw - math.pi / 2
            dx = xo * math.cos(theta) + yo * math.sin(theta)
            dy = -xo * math.sin(theta) + yo * math.cos(theta)

            if abs(dx) < C.W / 2 + C.EXTEND_BOUND and \
                    -C.LB - C.EXTEND_BOUND < dy < C.LF + C.EXTEND_BOUND:
                return False

    return True


def calc_rs_path_cost(rspath):
    cost = 0.0

    for lr in rspath.lengths:
        if lr >= 0:
            cost += 1
        else:
            cost += abs(lr) * C.BACKWARD_COST

    for i in range(len(rspath.lengths) - 1):
        if rspath.lengths[i] * rspath.lengths[i + 1] < 0.0:
            cost += C.GEAR_COST

    for ctype in rspath.ctypes:
        if ctype != "S":
            cost += C.STEER_ANGLE_COST * abs(C.MAX_STEER)

    nctypes = len(rspath.ctypes)
    ulist = [0.0 for _ in range(nctypes)]

    for i in range(nctypes):
        if rspath.ctypes[i] == "R":
            ulist[i] = -C.MAX_STEER
        elif rspath.ctypes[i] == "L":
            ulist[i] = C.MAX_STEER

    for i in range(nctypes - 1):
        cost += C.STEER_CHANGE_COST * abs(ulist[i + 1] - ulist[i])

    return cost


def calc_hybrid_cost(node, hmap, P):
    cost = node.cost + \
           C.H_COST * hmap[node.xind - P.minx][node.yind - P.miny]

    return cost


def calc_motion_set():
    s = np.arange(C.MAX_STEER / C.N_STEER,
                  C.MAX_STEER, C.MAX_STEER / C.N_STEER)

    steer = list(s) + [0.0] + list(-s)
    direc = [1.0 for _ in range(len(steer))] + [-1.0 for _ in range(len(steer))]
    steer = steer + steer

    return steer, direc


def is_same_grid(node1, node2):
    if node1.xind != node2.xind or \
            node1.yind != node2.yind or \
            node1.yawind != node2.yawind:
        return False

    return True


def calc_index(node, P):
    ind = (node.yawind - P.minyaw) * P.xw * P.yw + \
          (node.yind - P.miny) * P.xw + \
          (node.xind - P.minx)

    return ind


def calc_parameters(ox, oy, xyreso, yawreso, kdtree):
    minox, minoy = min(ox), min(oy)
    maxox, maxoy = max(ox), max(oy)

    ox.append(minox)
    oy.append(minoy)
    ox.append(maxox)
    oy.append(maxoy)

    minx = round(minox / xyreso)
    miny = round(minoy / xyreso)
    maxx = round(maxox / xyreso)
    maxy = round(maxoy / xyreso)

    xw, yw = maxx - minx, maxy - miny

    minyaw = round(-C.PI / yawreso) - 1
    maxyaw = round(C.PI / yawreso)
    yaww = maxyaw - minyaw

    P = Para(minx, miny, minyaw, maxx, maxy, maxyaw,
             xw, yw, yaww, xyreso, yawreso, ox, oy, kdtree)

    return P


def plot_car(x, y, yaw, steer):
    truckcolor = "-k"

    LENGTH = C.LB + C.LF

    truckOutLine = np.array([[-C.LB, (LENGTH - C.LB), (LENGTH - C.LB), (-C.LB), (-C.LB)],
                             [C.W / 2, C.W / 2, -C.W / 2, -C.W / 2, C.W / 2]])

    rr_wheel = np.array([[C.TR, -C.TR, -C.TR, C.TR, C.TR],
                         [-C.W / 12.0 + C.TW, -C.W / 12.0 + C.TW, C.W / 12.0 + C.TW,
                          C.W / 12.0 + C.TW, -C.W / 12.0 + C.TW]])

    rl_wheel = np.array([[C.TR, -C.TR, -C.TR, C.TR, C.TR],
                         [-C.W / 12.0 - C.TW, -C.W / 12.0 - C.TW, C.W / 12.0 - C.TW,
                          C.W / 12.0 - C.TW, -C.W / 12.0 - C.TW]])

    fr_wheel = np.array([[C.TR, -C.TR, -C.TR, C.TR, C.TR],
                         [-C.W / 12.0 + C.TW, -C.W / 12.0 + C.TW, C.W / 12.0 + C.TW,
                          C.W / 12.0 + C.TW, -C.W / 12.0 + C.TW]])

    fl_wheel = np.array([[C.TR, -C.TR, -C.TR, C.TR, C.TR],
                         [-C.W / 12.0 - C.TW, -C.W / 12.0 - C.TW, C.W / 12.0 - C.TW,
                          C.W / 12.0 - C.TW, -C.W / 12.0 - C.TW]])

    Rot1 = np.array([[math.cos(yaw), math.sin(yaw)],
                     [-math.sin(yaw), math.cos(yaw)]])

    Rot2 = np.array([[math.cos(-steer), math.sin(-steer)],
                     [-math.sin(-steer), math.cos(-steer)]])

    fr_wheel = (np.dot(fr_wheel.T, Rot2)).T
    fl_wheel = (np.dot(fl_wheel.T, Rot2)).T

    fr_wheel[0, :] = fr_wheel[0, :] + C.WB
    fl_wheel[0, :] = fl_wheel[0, :] + C.WB

    fr_wheel = (np.dot(fr_wheel.T, Rot1)).T
    fl_wheel = (np.dot(fl_wheel.T, Rot1)).T

    truckOutLine = (np.dot(truckOutLine.T, Rot1)).T
    rr_wheel = (np.dot(rr_wheel.T, Rot1)).T
    rl_wheel = (np.dot(rl_wheel.T, Rot1)).T

    truckOutLine[0, :] += x
    truckOutLine[1, :] += y
    fr_wheel[0, :] += x
    fr_wheel[1, :] += y
    rr_wheel[0, :] += x
    rr_wheel[1, :] += y
    fl_wheel[0, :] += x
    fl_wheel[1, :] += y
    rl_wheel[0, :] += x
    rl_wheel[1, :] += y

    plt.plot(truckOutLine[0, :], truckOutLine[1, :], truckcolor)
    plt.plot(fr_wheel[0, :], fr_wheel[1, :], truckcolor)
    plt.plot(rr_wheel[0, :], rr_wheel[1, :], truckcolor)
    plt.plot(fl_wheel[0, :], fl_wheel[1, :], truckcolor)
    plt.plot(rl_wheel[0, :], rl_wheel[1, :], truckcolor)
    plt.plot(x, y, "*")


def main():
    print("start!")
    x, y = 51, 31

    sx, sy = 5.0, 5.0
    syaw0 = np.deg2rad(90.0)

    gx, gy = 45.0, 10.0
    gyaw0 = np.deg2rad(89.0)

    ox, oy = [], []

    for i in range(x):
        ox.append(i)
        oy.append(0)
    for i in range(x):
        ox.append(i)
        oy.append(y - 1)
    for i in range(y):
        ox.append(0)
        oy.append(i)
    for i in range(y):
        ox.append(x - 1)
        oy.append(i)
    for i in range(10, 21):
        ox.append(i)
        oy.append(15)
    for i in range(15):
        ox.append(20)
        oy.append(i)
    for i in range(15, 30):
        ox.append(30)
        oy.append(i)
    for i in range(16):
        ox.append(40)
        oy.append(i)

    t0 = time.time()
    path = hybrid_astar_planning(sx, sy, syaw0, gx, gy, gyaw0,
                                 ox, oy, C.XY_RESO, C.YAW_RESO)
    t1 = time.time()
    print("running time: ", t1 - t0)

    if not path:
        print("Searching failed!")
        return

    plt.plot(ox, oy, ".k")
    plot_car(sx, sy, syaw0, 0.0)
    plot_car(gx, gy, gyaw0, 0.0)
    x = path.x
    y = path.y
    yaw = path.yaw
    direction = path.direction

    steer = 0.0
    for ii in range(len(x)):
        plt.cla()
        plt.plot(ox, oy, "sk")
        plt.plot(x, y, "-r", label="Hybrid A* path")

        if ii < len(x) - 2:
            k = (yaw[ii + 1] - yaw[ii]) / C.MOVE_STEP
            if ~direction[ii]:
                k *= -1
            steer = math.atan2(C.WB * k, 1.0)
        else:
            steer = 0.0
        plot_car(gx, gy, gyaw0, 0.0)
        plot_car(x[ii], y[ii], yaw[ii], steer)
        plt.axis("equal")
        plt.pause(0.0001)

    print("Done!")
    plt.axis("equal")
    plt.show()


if __name__ == '__main__':
    main()
