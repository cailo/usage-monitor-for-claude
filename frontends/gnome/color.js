/*
 * Usage Monitor for Claude - colour compatibility.
 *
 * GNOME Shell 47 removed Clutter.Color and merged it into Cogl.Color, which
 * expresses its components as 0-1 floats where the old type used 0-255 bytes.
 * Both types also reach JavaScript differently depending on how the binding
 * was generated: sometimes as readable struct fields, sometimes only through
 * getters. Reading a colour is therefore the one operation in this extension
 * that has to survive four combinations, which is why it lives here rather
 * than being open-coded next to every Cairo call.
 *
 * The failure this guards against is silent: an unreadable component yields
 * NaN, Cairo draws nothing, and no error is logged. Everything below is built
 * so a component can never leave this file as anything but a finite number.
 */
// Used when a colour cannot be read at all. Opaque magenta is deliberate: it
// is not a colour this design uses anywhere, so it reads as "something is
// wrong here" instead of quietly blending in.
const UNREADABLE = {red: 1, green: 0, blue: 1, alpha: 1};

const COMPONENTS = ['red', 'green', 'blue', 'alpha'];

/*
 * Set *color* as the Cairo source, scaling its alpha by *alphaScale*.
 *
 * @param {Cairo.Context} cr
 * @param {object} color - Cogl.Color, Clutter.Color, or a plain literal
 * @param {number} alphaScale - 0-1 multiplier applied to the alpha channel
 */
export function setSource(cr, color, alphaScale = 1) {
    const rgba = normalize(color);

    cr.setSourceRGBA(rgba.red, rgba.green, rgba.blue, rgba.alpha * alphaScale);
}

/*
 * Look up a custom `-usage-monitor-*` theme property, falling back to *fallback*.
 *
 * St.ThemeNode.lookup_color() returns [found, color]; a shell that changed
 * that shape, or a stylesheet the user replaced, must not take the panel down
 * with it.
 */
export function themeColor(node, property, fallback) {
    try {
        const result = node.lookup_color(property, true);
        if (Array.isArray(result) && result[0]) {
            return result[1];
        }
    } catch (error) {
        // Falls through to the caller's own colour.
    }

    return fallback;
}

/*
 * Read the foreground colour of *node*, or magenta when it cannot be read.
 */
export function foregroundColor(node) {
    try {
        return node.get_foreground_color();
    } catch (error) {
        return UNREADABLE;
    }
}

/*
 * Reduce any colour representation to {red, green, blue, alpha} in 0-1.
 */
function normalize(color) {
    if (!color) {
        return UNREADABLE;
    }

    const raw = {};
    for (const name of COMPONENTS) {
        const value = readComponent(color, name);
        if (value === null) {
            return UNREADABLE;
        }
        raw[name] = value;
    }

    // Byte-range detection has to look at the whole colour, not one component:
    // a 0-255 colour whose red happens to be 0 is indistinguishable from a
    // float one until a sibling component exceeds 1.
    const isByteRange = COMPONENTS.some(name => raw[name] > 1);
    const divisor = isByteRange ? 255 : 1;

    const rgba = {};
    for (const name of COMPONENTS) {
        rgba[name] = clamp(raw[name] / divisor);
    }

    return rgba;
}

/*
 * Read one component as a finite number, or null when it cannot be read.
 *
 * The struct field is tried first because it is what both colour types expose
 * when the binding allows it; the getter is the fallback for the versions
 * where the fields are not introspectable and a plain read yields undefined.
 */
function readComponent(color, name) {
    const field = color[name];
    if (typeof field === 'number' && Number.isFinite(field)) {
        return field;
    }

    const getter = color[`get_${name}`];
    if (typeof getter === 'function') {
        try {
            const value = getter.call(color);
            if (typeof value === 'number' && Number.isFinite(value)) {
                return value;
            }
        } catch (error) {
            return null;
        }
    }

    return null;
}

function clamp(value) {
    return Math.max(0, Math.min(1, value));
}
