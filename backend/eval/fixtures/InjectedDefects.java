package za.ac.cput.eval;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import org.apache.commons.codec.digest.DigestUtils;

/** Evaluation fixture: defects carry a GT marker (ground truth); decoys carry a TN marker (must NOT be flagged). */
public class InjectedDefects {
    private Connection conn;

    // ---- CWE-798 hard-coded credentials
    String apiKey = "sk_live_9f8a7b6c5d4e3f2a";            // GT:CWE-798
    String dbPassword = "Adm1n#2026!";                      // GT:CWE-798
    String clientSecret = "c0ffee-0000-secret-value";       // GT:CWE-798
    String okPassword = System.getenv("OK_PASSWORD");       // TN
    String passwordLabel = "Password";                      // TN (UI label, not a credential)
    String tokenType = "Bearer";                            // TN

    // ---- CWE-89 SQL injection
    public ResultSet findOrder(Statement stmt, String id) throws SQLException {
        ResultSet orders = stmt.executeQuery("SELECT * FROM orders WHERE id = " + id);   // GT:CWE-89
        return orders;
    }

    public ResultSet findCustomer(Statement stmt, String email) throws SQLException {
        ResultSet cust = stmt.executeQuery("SELECT * FROM customers WHERE email = " + email);   // GT:CWE-89
        return cust;
    }

    public int deleteCart(Statement stmt, String id) throws SQLException {
        int n = stmt.executeUpdate("DELETE FROM carts WHERE id = " + id);   // GT:CWE-89
        return n;
    }

    public ResultSet safeLookup(String id) throws SQLException {
        java.sql.PreparedStatement ps = conn.prepareStatement("SELECT * FROM orders WHERE id = ?");   // TN
        ps.setString(1, id);
        return ps.executeQuery();
    }

    // ---- CWE-916 weak password storage
    public String hashA(String pw) { String h1 = DigestUtils.md5Hex(pw); return h1; }     // GT:CWE-916
    public String hashB(String pw) { String h2 = DigestUtils.sha1Hex(pw); return h2; }    // GT:CWE-916
    public String hashC(String pw) { String h3 = DigestUtils.md5Hex(pw + "x"); return h3; }   // GT:CWE-916
    public String checksum(byte[] data) { return DigestUtils.sha256Hex(data); }   // TN (not password storage)
}
