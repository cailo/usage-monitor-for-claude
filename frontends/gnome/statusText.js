/*
 * Usage Monitor for Claude - footer status text.
 *
 * The daemon sends two timestamps and the translated templates; turning them
 * into "Updated 2m ago · Next update in 3m" is the frontend's job, and it runs
 * once a second for as long as the menu stays open.
 *
 * Kept free of any gi:// import on purpose. Time arithmetic and template
 * substitution are exactly the kind of logic that fails on a boundary rather
 * than loudly, so this module can be executed and tested with plain Node -
 * see tests/test_gnome_js.py. Anything needing St or Cairo stays in
 * indicator.js.
 */

const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_MINUTE = 60;

/*
 * Build the footer line.
 *
 * @param {object|null} status - the snapshot's `status` section
 * @param {object} labels - the snapshot's translated `labels` section
 * @param {number} nowSeconds - current time as a Unix timestamp
 * @returns {string}
 */
export function formatStatus(status, labels, nowSeconds) {
    if (!status) {
        return '';
    }

    // A hard error replaces the line: there is no "last updated" worth
    // reporting next to a fetch that never produced data.
    if (status.is_error) {
        return status.text || '';
    }
    if (status.refreshing && !status.last_success_time) {
        return label(labels, 'status_refreshing');
    }
    if (status.error) {
        return status.error;
    }

    let text = '';

    if (status.last_success_time) {
        const elapsed = Math.max(0, Math.round(nowSeconds - status.last_success_time));
        text = elapsed < SECONDS_PER_MINUTE
            ? substitute(label(labels, 'status_updated_s'), {s: elapsed})
            : substitute(label(labels, 'status_updated'), {duration: formatDuration(elapsed, labels)});
    }

    if (status.next_poll_time) {
        // Clamped at zero: a poll that is already due would otherwise count
        // into negative numbers until the daemon gets round to it.
        const remaining = Math.max(0, Math.round(status.next_poll_time - nowSeconds));
        const next = substitute(label(labels, 'status_next_update'), {duration: formatDuration(remaining, labels)});
        text = text ? `${text} · ${next}` : next;
    }

    return text;
}

/*
 * Render *seconds* using the coarsest template that still carries meaning.
 *
 * @param {number} seconds
 * @param {object} labels
 * @returns {string}
 */
export function formatDuration(seconds, labels) {
    const hours = Math.floor(seconds / SECONDS_PER_HOUR);
    const minutes = Math.floor((seconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);

    if (hours > 0) {
        return substitute(label(labels, 'duration_hm'), {h: hours, m: minutes});
    }
    if (minutes > 0) {
        return substitute(label(labels, 'duration_m'), {m: minutes});
    }

    return substitute(label(labels, 'duration_s'), {s: seconds});
}

function label(labels, key) {
    return labels && labels[key] ? labels[key] : '';
}

/*
 * Replace every `{name}` in *template* with its value.
 *
 * Any placeholder left without a value is dropped rather than printed: a
 * snapshot from an older daemon can be missing a template, and a literal
 * "{duration}" in the panel is worse than a slightly short sentence.
 */
function substitute(template, values) {
    return template.replace(/\{(\w+)\}/g, (match, name) => {
        const value = values[name];
        return value === undefined ? '' : String(value);
    });
}
