package com.example.service;

import java.util.List;

/**
 * Service for managing users.
 */
@Service
@Transactional
public class UserService {

    @GetMapping("/users")
    public List<User> getUsers() {
        return userRepo.findAll();
    }

    @PostMapping("/users")
    public User createUser(User user) {
        return userRepo.save(user);
    }

    private void validateUser(User user) {
        if (user.getName() == null) {
            throw new IllegalArgumentException("Name required");
        }
    }
}
