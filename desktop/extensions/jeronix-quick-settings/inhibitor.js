// SPDX-License-Identifier: GPL-3.0-or-later
//
// Session idle/suspend inhibition through the public org.gnome.SessionManager
// D-Bus API. Kept free of GNOME Shell imports so it can be unit-tested with
// plain gjs (see tests/unit/js/test_inhibitor.js).

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

// Flags from org.gnome.SessionManager.Inhibit.
export const InhibitFlags = Object.freeze({
    LOGOUT: 1,
    SWITCH_USER: 2,
    SUSPEND: 4,
    IDLE: 8,
});

const BUS_NAME = 'org.gnome.SessionManager';
const OBJECT_PATH = '/org/gnome/SessionManager';
const INTERFACE = 'org.gnome.SessionManager';

function callAsync(connection, method, params, replyType) {
    return new Promise((resolve, reject) => {
        connection.call(BUS_NAME, OBJECT_PATH, INTERFACE, method, params,
            replyType, Gio.DBusCallFlags.NONE, -1, null,
            (conn, res) => {
                try {
                    resolve(conn.call_finish(res));
                } catch (e) {
                    reject(e);
                }
            });
    });
}

/**
 * Talks to the real session manager. Any object with the same two async
 * methods can be passed to Inhibitor instead (used by the unit tests).
 *
 * @param {Gio.DBusConnection} connection
 */
export function createSessionManagerClient(connection = Gio.DBus.session) {
    return {
        async inhibit(appId, reason, flags) {
            const reply = await callAsync(connection, 'Inhibit',
                new GLib.Variant('(susu)', [appId, 0, reason, flags]),
                new GLib.VariantType('(u)'));
            return reply.deepUnpack()[0];
        },
        async uninhibit(cookie) {
            await callAsync(connection, 'Uninhibit',
                new GLib.Variant('(u)', [cookie]), null);
        },
    };
}

/**
 * Holds at most one inhibition cookie and reconciles it with the requested
 * state. Requests may overlap (a user can toggle faster than D-Bus answers),
 * so the outcome of each call is checked against the latest request.
 */
export class Inhibitor {
    /**
     * @param {object} client - see createSessionManagerClient()
     * @param {object} options
     * @param {string} options.appId
     * @param {string} options.reason
     * @param {number} options.flags - InhibitFlags bitmask
     * @param {Function} [options.onChanged] - (active, error) => void
     */
    constructor(client, {appId, reason, flags, onChanged = () => {}}) {
        this._client = client;
        this._appId = appId;
        this._reason = reason;
        this._flags = flags;
        this._onChanged = onChanged;
        this._cookie = null;
        this._wanted = false;
        this._pending = false;
        this._destroyed = false;
    }

    get active() {
        return this._cookie !== null;
    }

    get wanted() {
        return this._wanted;
    }

    enable() {
        if (this._destroyed)
            return Promise.resolve();
        this._wanted = true;
        return this._sync();
    }

    disable() {
        this._wanted = false;
        return this._sync();
    }

    /** Releases any held inhibition. The object is unusable afterwards. */
    destroy() {
        this._destroyed = true;
        this._onChanged = () => {};
        return this.disable();
    }

    async _sync() {
        // A running _sync loops until state matches the latest request.
        if (this._pending)
            return;
        this._pending = true;
        try {
            while (this._wanted !== this.active) {
                if (this._wanted)
                    await this._acquire();
                else
                    await this._release();
            }
        } finally {
            this._pending = false;
        }
    }

    async _acquire() {
        try {
            this._cookie = await this._client.inhibit(
                this._appId, this._reason, this._flags);
            this._onChanged(true, null);
        } catch (e) {
            this._wanted = false;
            this._onChanged(false, e);
        }
    }

    async _release() {
        const cookie = this._cookie;
        // Forget the cookie even if the call fails: the session manager also
        // drops inhibitors when our bus connection goes away, and retrying a
        // rejected cookie forever would wedge the toggle.
        this._cookie = null;
        try {
            await this._client.uninhibit(cookie);
            this._onChanged(false, null);
        } catch (e) {
            this._onChanged(false, e);
        }
    }
}
