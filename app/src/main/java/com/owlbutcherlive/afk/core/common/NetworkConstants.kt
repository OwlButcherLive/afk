package com.owlbutcherlive.afk.core.common

/**
 * Network constants used throughout the app.
 * All local endpoints go through the SSH forwarded port.
 */
object NetworkConstants {
    const val DEFAULT_LOCAL_FORWARD_PORT = 3344
    const val DEFAULT_SSH_PORT = 22
    const val LOCALHOST = "127.0.0.1"

    fun baseUrl(port: Int): String = "http://$LOCALHOST:$port/"
}
