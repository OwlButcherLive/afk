package com.owlbutcherlive.afk.core.ssh

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import net.schmizz.sshj.SSHClient
import net.schmizz.sshj.common.SecurityUtils
import net.schmizz.sshj.connection.channel.direct.LocalPortForwarder
import net.schmizz.sshj.connection.channel.direct.Parameters
import net.schmizz.sshj.transport.verification.PromiscuousVerifier
import net.schmizz.sshj.userauth.keyprovider.OpenSSHKeyFile
import java.net.InetSocketAddress
import java.net.ServerSocket

/**
 * Manages SSH connections with local port forwarding tunnels.
 *
 * Lifecycle: connect -> forward -> observe -> close -> cleanup.
 */
class TunnelManager {

    companion object {
        private const val TAG = "TunnelManager"

        init {
            // Tell SSHJ to skip Bouncy Castle provider registration.
            // Android's bundled BC provider (boot classloader) is stripped and
            // doesn't include X25519 or EC algorithms. SSHJ's SecurityUtils
            // would find the system BC and fail on any crypto call using those
            // algorithms. Instead, we rely on Android's Conscrypt/AndroidOpenSSL
            // provider which handles all algorithms SSHJ needs (DH, EC, ECDH).
            SecurityUtils.setRegisterBouncyCastle(false)
        }
    }

    private val _connectionState = MutableStateFlow<SshConnectionResult>(SshConnectionResult.Disconnected)
    val connectionState: StateFlow<SshConnectionResult> = _connectionState.asStateFlow()

    private var sshClient: SSHClient? = null
    private var forwarderThread: Thread? = null
    private var serverSocket: ServerSocket? = null

    /**
     * Connect to the remote host and set up local port forwarding.
     */
    suspend fun connect(config: SshConfig): SshConnectionResult = withContext(Dispatchers.IO) {
        _connectionState.value = SshConnectionResult.Connecting
        Log.d(TAG, "Connecting to ${config.host}:${config.port}...")

        try {
            val client = SSHClient()
            client.addHostKeyVerifier(PromiscuousVerifier())
            client.connect(config.host, config.port)
            client.timeout = config.timeoutSeconds * 1000

            // Authenticate
            when {
                config.password != null -> {
                    client.authPassword(config.username, config.password)
                    Log.d(TAG, "Authenticated with password")
                }

                config.privateKeyPem != null -> {
                    val keyProvider = OpenSSHKeyFile()
                    keyProvider.init(
                        config.privateKeyPem,
                        config.privateKeyPassphrase ?: ""
                    )
                    client.authPublickey(config.username, keyProvider)
                    Log.d(TAG, "Authenticated with private key")
                }

                else -> {
                    throw IllegalStateException("No authentication method provided")
                }
            }

            sshClient = client

            // Set up local port forwarding
            val localPort = setupLocalPortForwarding(client, config.localForwardPort, config.remoteForwardPort)

            val result = SshConnectionResult.Connected(localPort)
            _connectionState.value = result
            Log.d(TAG, "Connected. Tunnel: localhost:$localPort -> remote:localhost:${config.remoteForwardPort}")
            result
        } catch (e: Exception) {
            Log.e(TAG, "Connection failed: ${e.message}", e)
            cleanup()
            val result = SshConnectionResult.Failed(
                message = formatErrorMessage(e),
                throwable = e
            )
            _connectionState.value = result
            result
        }
    }

    /**
     * Disconnect the SSH session and clean up resources.
     */
    suspend fun disconnect() = withContext(Dispatchers.IO) {
        Log.d(TAG, "Disconnecting...")
        cleanup()
        _connectionState.value = SshConnectionResult.Disconnected
    }

    /**
     * Clean up all resources.
     */
    private fun cleanup() {
        try {
            forwarderThread?.interrupt()
            forwarderThread = null
        } catch (_: Exception) {}

        try {
            serverSocket?.close()
            serverSocket = null
        } catch (_: Exception) {}

        try {
            sshClient?.disconnect()
            sshClient = null
        } catch (_: Exception) {}
    }

    /**
     * Set up a local port forwarding tunnel.
     * Listens on localhost:localPort and forwards to remote localhost:remotePort through the SSH connection.
     */
    private fun setupLocalPortForwarding(
        client: SSHClient,
        localPort: Int,
        remotePort: Int
    ): Int {
        val serverSock = ServerSocket()
        serverSocket = serverSock
        try {
            // Try the requested port first
            serverSock.bind(InetSocketAddress("127.0.0.1", localPort))
        } catch (e: java.net.BindException) {
            // Port is busy (e.g. ADB reverse) — let the OS pick a free one
            Log.w(TAG, "Port $localPort in use, binding to ephemeral port instead")
            serverSock.bind(InetSocketAddress("127.0.0.1", 0))
        }
        val actualPort = serverSock.localPort

        val params = Parameters("127.0.0.1", actualPort, "127.0.0.1", remotePort)

        val forwarder = client.newLocalPortForwarder(params, serverSock)

        forwarderThread = Thread {
            try {
                forwarder.listen()
            } catch (e: Exception) {
                if (!Thread.currentThread().isInterrupted) {
                    Log.w(TAG, "Forwarder error: ${e.message}")
                }
            }
        }.also {
            it.isDaemon = true
            it.start()
        }

        return actualPort
    }

    /**
     * Format SSH errors into user-friendly messages.
     */
    private fun formatErrorMessage(e: Exception): String = when {
        e.message?.contains("Auth fail") == true ||
        e.message?.contains("authentication") == true ->
            "Authentication failed. Check your credentials."
        e.message?.contains("Connection refused") == true ||
        e.message?.contains("Connection timed out") == true ->
            "Could not connect to the remote host. Check the host and port."
        e.message?.contains("UnknownHostException") == true ||
        e.message?.contains("unable to resolve host") == true ->
            "Host not found. Check the hostname or IP address."
        e.message?.contains("key") == true ||
        e.message?.contains("Key") == true ->
            "Invalid private key format or passphrase."
        else -> "Connection failed: ${e.message ?: "Unknown error"}"
    }

    /**
     * Clean up when the manager is no longer needed.
     */
    fun onDestroy() {
        cleanup()
    }
}
