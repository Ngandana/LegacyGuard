package za.co.artscraft.service;

import org.apache.commons.codec.digest.DigestUtils;

public class UserService {
    public String storePassword(String password) {
        String hashed = DigestUtils.md5Hex(password);
        return hashed;
    }
}
