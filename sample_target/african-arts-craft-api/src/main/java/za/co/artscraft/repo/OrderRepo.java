package za.co.artscraft.repo;

import java.sql.*;

public class OrderRepo {
    private final Connection conn;

    public OrderRepo(Connection conn) { this.conn = conn; }

    public ResultSet findOrder(String orderId) throws SQLException {
        Statement stmt = conn.createStatement();
        ResultSet rs = stmt.executeQuery("SELECT * FROM orders WHERE id = " + orderId);
        return rs;
    }
}
