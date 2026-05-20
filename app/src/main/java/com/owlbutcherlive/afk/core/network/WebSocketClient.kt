package com.owlbutcherlive.afk.core.network

import android.util.Log
import com.owlbutcherlive.afk.core.common.NetworkConstants
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit

/**
 * Manages a WebSocket connection through the SSH forwarded tunnel.
 * For receiving real-time events from the Agent Gateway.
 */
class WebSocketClient {

    companion object {
        private const val TAG = "WebSocketClient"
    }

    private var webSocket: WebSocket? = null
    private var okHttpClient: OkHttpClient? = null

    private val _messages = Channel<String>(Channel.BUFFERED)
    val messages: Flow<String> = _messages.receiveAsFlow()

    private val _connectionEvents = Channel<WebSocketEvent>(Channel.CONFLATED)
    val connectionEvents: Flow<WebSocketEvent> = _connectionEvents.receiveAsFlow()

    sealed interface WebSocketEvent {
        data object Connected : WebSocketEvent
        data class Disconnected(val code: Int, val reason: String) : WebSocketEvent
        data class Failed(val message: String) : WebSocketEvent
    }

    /**
     * Connect to a WebSocket endpoint on the forwarded local port.
     */
    fun connect(port: Int = NetworkConstants.DEFAULT_LOCAL_FORWARD_PORT, path: String = "/ws") {
        disconnect()

        val client = OkHttpClient.Builder()
            .readTimeout(0, TimeUnit.MILLISECONDS) // no read timeout for long-lived WS
            .build()
            .also { okHttpClient = it }

        val request = Request.Builder()
            .url("ws://${NetworkConstants.LOCALHOST}:$port$path")
            .build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d(TAG, "WebSocket connected")
                _connectionEvents.trySend(WebSocketEvent.Connected)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.d(TAG, "WebSocket message: $text")
                _messages.trySend(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket closing: $code $reason")
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket closed: $code $reason")
                _connectionEvents.trySend(WebSocketEvent.Disconnected(code, reason))
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket failure: ${t.message}", t)
                _connectionEvents.trySend(WebSocketEvent.Failed(t.message ?: "Unknown error"))
            }
        })
    }

    /**
     * Send a message through the WebSocket.
     */
    fun send(message: String): Boolean {
        return webSocket?.send(message) ?: false
    }

    /**
     * Disconnect the WebSocket.
     */
    fun disconnect() {
        webSocket?.close(1000, "Client closing")
        webSocket = null
        okHttpClient?.dispatcher?.executorService?.shutdown()
        okHttpClient = null
    }
}
