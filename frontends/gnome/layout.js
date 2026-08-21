/*
 * Usage Monitor for Claude - layout compatibility.
 *
 * St.BoxLayout became Clutter.Orientable in GNOME 47, and the `vertical`
 * construct property it replaced is on its way out. Deciding between the two
 * here, once, keeps a single copy of the extension working across the shell
 * versions listed in metadata.json instead of shipping one file per release.
 */
import Clutter from 'gi://Clutter';
import St from 'gi://St';

export function verticalBox(properties = {}) {
    const box = new St.BoxLayout(properties);

    if (typeof box.set_orientation === 'function') {
        box.set_orientation(Clutter.Orientation.VERTICAL);
    } else {
        box.vertical = true;
    }

    return box;
}

export function horizontalBox(properties = {}) {
    return new St.BoxLayout(properties);
}
